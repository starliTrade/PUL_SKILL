"""
PULSAR P1.14 — Referee Oracle signing service.

Design (P1.14):
- The signing key is pluggable (audit H-07, 2026-10-22): `api/signer.py`
  provides `ORACLE_SIGNER=local` (a key in env, for dev), `aws-kms` and
  `gcp-kms`, where the private key never enters this process. The oracle asks
  the signer for a digest signature and for the address; nothing else changes.
- The default is `local` only because changing it would break existing
  deployments silently. Production deployments are expected to set a KMS mode —
  docs/DEPLOYMENT.md §2 and the readiness checklist say so.
- It signs ONLY settlements produced by the authoritative engine (P1.13),
  never raw client claims.
- Replay protection: every settlement is bound to matchId, winner, validated
  reaction times, a per-settlement nonce, an expiry deadline, the chain id,
  and the escrow contract address — exactly the fields settleDuel() hashes.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

import signer as _signer
import timebase
from eth_account import Account

# EIP-191 personal-message prefix the contract applies before ecrecover.
_EIP191_PREFIX = b"\x19Ethereum Signed Message:\n32"

# Deadline for on-chain submission of a signed settlement.
SETTLEMENT_DEADLINE_SECONDS = 600  # 10 minutes — MAXIMUM validity of a
# settlement signature. Audit #10 (item 5): the signature deadline must never
# outlive the on-chain refund horizon (activation + the contract's
# MATCH_TIMEOUT = 30 min — single source of truth: match_engine).
# sign_settlement() clamps every deadline to match_engine.settlement_deadline,
# so a re-signed envelope minted at minute 29 expires WITH the duel instead of
# dangling past the refund horizon as a proof nobody can spend. — MAXIMUM validity of a
# settlement signature. Audit #10 (item 5): the signature deadline must never
# outlive the on-chain refund horizon (activation + the contract's
# MATCH_TIMEOUT = 30 min, single source of truth: match_engine). sign_settlement
# clamps every deadline to match_engine.settlement_deadline(matchish), so a
# re-signed envelope minted at minute 29 expires with the duel instead of
# dangling past the refund horizon (a proof nobody can spend).

_KMS_KEY_ENV = "ORACLE_PRIVATE_KEY"
# P0-fix: the signing chain id MUST match the chain the CLIENT plays on, not
# a hardcoded mainnet value. settleDuel() hashes block.chainid, so a signature
# minted for 137 is rejected on Amoy (80002) and vice versa. The deploy env
# sets ORACLE_CHAIN_ID to the target chain; the default follows the client
# default (src/lib/chain.ts → Amoy testnet) so rehearsal works out of the box.
_DEFAULT_CHAIN_ID = int(os.environ.get("ORACLE_CHAIN_ID", "80002"))


_signer_cache: Account | None = None
_signer_cache_key: str | None = None


def reset_signer_cache() -> None:
    """Test seam: forget the cached signer."""
    global _signer_cache, _signer_cache_key
    _signer_cache = None
    _signer_cache_key = None


def load_signer() -> Account:
    """The referee signer, loaded ONCE (audit M8).

    `Account.from_key` performs an EC scalar multiplication — the expensive part
    of signing — and this used to run on every signature. Cached per key, so a
    key rotation is still picked up.
    """
    global _signer_cache, _signer_cache_key
    key = os.environ.get(_KMS_KEY_ENV, "")
    if _signer_cache is not None and _signer_cache_key == key:
        return _signer_cache
    _signer_cache = _load_signer()
    _signer_cache_key = key
    return _signer_cache


def _load_signer() -> Account:
    key = os.environ.get(_KMS_KEY_ENV, "")
    if not key:
        raise RuntimeError(
            f"{_KMS_KEY_ENV} is required for the referee oracle. In production, "
            "provide it via KMS and adapt _load_signer() accordingly."
        )
    return Account.from_key(key if key.startswith("0x") else f"0x{key}")


def oracle_address() -> str:
    """The address the escrow must trust. Works for every signer backend."""
    if _signer.mode() != "local":
        return _signer.get_signer().address
    # eth_account's stub omits `.address`; the runtime object always has it.
    return str(load_signer().address)  # type: ignore[attr-defined]


def sign_digest(digest: bytes) -> bytes:
    """Sign a 32-byte digest, whichever backend is configured (audit H-07).

    `local` keeps the in-process path (and its cached Account); KMS backends go
    through `api/signer.py`, so the private key never exists here.
    """
    if _signer.mode() != "local":
        return _signer.get_signer().sign_digest(digest)
    signed = _sign_hash_bytes(load_signer(), digest)
    raw = bytes(signed.signature) if not isinstance(signed.signature, bytes) else signed.signature
    return _signature_to_low_s_bytes(raw)


# secp256k1 group order — needed for low-s (EIP-2) normalization, which the
# hardened escrow contract enforces on-chain.
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_SECP256K1_HALF_N = _SECP256K1_N // 2


def _signature_to_low_s_bytes(raw: bytes) -> bytes:
    """Normalize a 65-byte (r, s, v) signature to low-s form."""
    if len(raw) != 65:
        raise ValueError("expected 65-byte signature")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:64], "big")
    v = raw[64]
    # Audit M6: `v` was never validated. A raw recovery id (0/1) or any other
    # byte passed straight through and reached the CONTRACT, which rejects it —
    # so the failure surfaced as an on-chain revert AFTER a settlement was
    # announced. Reject it here, where the caller can still do something.
    if v not in (27, 28):
        raise ValueError(f"invalid signature v value: {v} (expected 27 or 28)")
    if s > _SECP256K1_HALF_N:
        s = _SECP256K1_N - s
        # Audit M6 (found by the test): this was `v ^= 0x01` with a comment
        # claiming it "flips 27<->28". It does not — 27 ^ 1 is 26, which the
        # contract rejects. The recovery id is `v - 27`, so flipping it means
        # `v = 27 + (1 - (v - 27))` = `55 - v`.
        v = 55 - v
    return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])


def _sign_hash_bytes(account: Account, digest: bytes):
    """eth-account renamed signHash across versions; support them all."""
    if hasattr(account, "unsafe_sign_hash"):
        return account.unsafe_sign_hash(digest)
    if hasattr(account, "signHash"):
        return account.signHash(digest)
    if hasattr(account, "sign_hash"):
        return account.sign_hash(digest)
    raise RuntimeError("No hash-signing API available in this eth-account version")


def _keccak(data: bytes) -> bytes:
    from Crypto.Hash import keccak  # pycryptodome

    k = keccak.new(digest_bits=256)
    k.update(data)
    return k.digest()


def _uint256(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _address_bytes20(address: str) -> bytes:
    """
    Address as its RAW 20 bytes — matches Solidity abi.encodePacked(address),
    which packs addresses WITHOUT left-padding. (A previous version padded to
    32 bytes here, which made every oracle signature invalid on-chain.)
    """
    clean = address.lower().removeprefix("0x")
    if len(clean) != 40:
        raise ValueError(f"bad address: {address}")
    return bytes.fromhex(clean)


# Back-compat alias for callers/tests.
_address_bytes32 = _address_bytes20


def _match_id_bytes32(match_id: str) -> bytes:
    """The 32-byte id the contract uses, from a server match id.

    Convention (audit M19): a 64-character HEX id is decoded as bytes; anything
    else is hashed. The old code checked only the LENGTH, so a 64-character
    non-hex id hit `bytes.fromhex` and raised — taking the signing path down.
    The hash branch has to actually be reachable.
    """
    clean = match_id.lower().removeprefix("0x")
    if len(clean) == 64 and all(c in "0123456789abcdef" for c in clean):
        return bytes.fromhex(clean)
    # Server-generated match ids are free-form; hash them into the 32-byte id
    # the client must also use when calling createDuel/joinDuel.
    return hashlib.sha256(match_id.encode("utf-8")).digest()


def build_settlement_digest(
    record: dict[str, Any],
    server_nonce: int,
    chain_id: int = _DEFAULT_CHAIN_ID,
    escrow_address: str = "",
) -> bytes:
    # `chain_id` defaults to the env-configured deployment chain (see
    # _DEFAULT_CHAIN_ID above). Never hardcode 137 at call sites — the client
    # (src/lib/chain.ts) and this signer must always agree.
    """
    EXACT digest preimage verified by PulsarEscrow.settleDuel():

      keccak256("\\x19Ethereum Signed Message:\\n32" +
        keccak256(abi.encodePacked(
          matchId, winner, winnerTimeMs, loserTimeMs,
          nonce, deadline, block.chainid, address(escrow))))

    Any mismatch here means the contract will reject the signature.
    """
    if not escrow_address:
        escrow_address = os.environ.get("ESCROW_ADDRESS", "")
    if not escrow_address:
        raise RuntimeError("ESCROW_ADDRESS is required to bind settlements to the escrow")

    # EXACT Solidity abi.encodePacked layout from PulsarEscrow.settleDuel():
    #   bytes32 (32) | address (raw 20) | uint256 (32) x5 | address (raw 20)
    packed = b"".join(
        [
            _match_id_bytes32(str(record["matchId"])),
            _address_bytes20(str(record["winner"])),
            _uint256(int(record["winnerTimeMs"])),
            _uint256(int(record["loserTimeMs"])),
            _uint256(int(server_nonce)),
            _uint256(int(record["deadline"])),
            _uint256(int(chain_id)),
            _address_bytes20(escrow_address),
        ]
    )
    inner = _keccak(packed)
    return _keccak(_EIP191_PREFIX + inner)


def sign_settlement(
    record: dict[str, Any],
    chain_id: int | None = None,
    matchish: Any = None,
) -> dict[str, Any]:
    """
    Sign one engine-produced settlement. The record MUST come from
    match_engine.settle(), not from client input. `chain_id` overrides the
    env-configured deployment chain (used by tests); production callers omit
    it so the signer and the deployed escrow always share ORACLE_CHAIN_ID.
    """
    # Audit M7: the shape checks below prove the record LOOKS like engine
    # output. They cannot prove it IS — any caller that can build a dict with
    # these keys got a signature over real money. The engine stamps its records
    # and the stamp is a MAC, so it cannot be forged by a caller.
    import match_engine as _engine

    if not _engine.settlement_is_stamped(record):
        raise ValueError(
            "Refusing to sign: record carries no valid engine stamp "
            "(only match_engine.settle() output may be signed)"
        )
    if record.get("status") != "settled":
        raise ValueError("Refusing to sign: settlement status is not 'settled'")
    if not record.get("winner"):
        raise ValueError("Refusing to sign: settlement has no winner")
    validated = record.get("validatedTimes") or {}
    if not validated or any(not times for times in validated.values()):
        raise ValueError(
            "Refusing to sign: record lacks engine-validated round data "
            "(only match_engine.settle() output may be signed)"
        )

    server_nonce = secrets.randbelow(2**48)

    # THE DEADLINE IS ANCHORED TO THE CHAIN, NOT TO THIS PROCESS.
    #
    # Audit 2026-10-15 (found by a time-travel test, and left open until now):
    # this used `timebase.now()` — the SERVER's clock — while the contract
    # enforces `block.timestamp <= proof.deadline` on the CHAIN's. A drift larger
    # than the deadline window makes every proof arrive ALREADY EXPIRED:
    # settlement becomes impossible, the winner cannot claim, and the only
    # remaining path is the refund — which pays both players and takes the win
    # away from the player who earned it.
    #
    # So the clock is read from the chain the contract will use. If it cannot be
    # read, fall back to the local clock and say so, because refusing to sign
    # would be worse than a deadline that might be slightly off.
    # Imported locally: `onchain` imports this module, so a module-level import
    # would be a cycle. The same pattern is already used for `match_engine`.
    _onchain: Any = None
    try:
        import onchain as _onchain_mod

        _onchain = _onchain_mod
    except Exception:  # noqa: BLE001
        pass
    chain_now = _onchain.chain_now() if _onchain is not None else None
    base = chain_now if chain_now is not None else int(timebase.now())
    deadline = int(base) + SETTLEMENT_DEADLINE_SECONDS

    # Clamp to the on-chain refund horizon. Audit #10 (item 5): without the clamp,
    # a re-sign issued near minute 30 would mint a proof valid past the moment the
    # contract refunds both stakes.
    if matchish is not None:
        try:
            import match_engine as _me

            # Audit H-25: `settlement_deadline` now RAISES when the match carries
            # no timestamps instead of returning a 1970 horizon. Raising here is
            # caught by the enclosing `except` and means "no clamp", which is the
            # correct behaviour: a 10-minute proof is still bounded, and refusing
            # to sign would strand the winner over a missing field.
            horizon = _me.settlement_deadline_or_none(matchish)
            # The horizon is derived from the match's own activation instant. When
            # the chain can tell us that instant directly, prefer it — the server's
            # record and the contract's cannot then disagree.
            match_id = getattr(matchish, "match_id", "")
            if match_id and _onchain is not None:
                # Mirror the contract's clock origin. It computes
                # `max(activatedAt, createdAt)` — and because `joinDuel` sets
                # `activatedAt` strictly AFTER `createDuel` set `createdAt`
                # (PulsarEscrow.sol:337, 367), that max is ALWAYS `activatedAt`.
                #
                # Corrected 2026-10-16: the first version of this comment claimed
                # a duel could have `createdAt > activatedAt`. It cannot. Reading
                # `createdAt` as well cost a second eth_call inside the store
                # transaction for a branch that never occurs.
                activated = _onchain.duel_activated_at(str(match_id))
                if activated is not None:
                    horizon = int(activated) + _me.MATCH_TIMEOUT_SECONDS
            if horizon is not None:
                deadline = min(deadline, horizon)
        except Exception:  # noqa: BLE001 — clamping must never block settlement
            pass

    # Compare against the SAME clock the deadline was built from. Comparing a
    # chain-anchored deadline to a server-anchored `now` would reintroduce the
    # drift this whole block exists to remove.
    if deadline <= int(base):
        raise ValueError(
            "Refusing to sign: the on-chain MATCH_TIMEOUT has elapsed — "
            "this duel can only refund via refundTimeoutMatch."
        )

    digest = build_settlement_digest(
        {
            "matchId": record["matchId"],
            "winner": record["winner"],
            "winnerTimeMs": record["winnerTimeMs"],
            "loserTimeMs": record["loserTimeMs"],
            "deadline": deadline,
        },
        server_nonce,
        chain_id=_DEFAULT_CHAIN_ID if chain_id is None else int(chain_id),
    )
    low_s = sign_digest(digest)
    signature = "0x" + low_s.hex()

    return {
        "matchId": record["matchId"],
        "winner": record["winner"],
        "winnerTimeMs": record["winnerTimeMs"],
        "loserTimeMs": record["loserTimeMs"],
        "serverNonce": server_nonce,
        "deadline": deadline,
        "oracleAddress": oracle_address(),
        "signature": signature,
        "validatedTimes": record.get("validatedTimes", {}),
        # Audit 2026-10-13: the engine declares forfeits in its result
        # (`forfeits: {addr: bool}`), but the packet dropped the field, so
        # `economy.record_settlement` read an empty map and recorded
        # `forfeit: false` for every duel — including forfeits. The ledger then
        # disagreed with what actually happened. (Not part of the signed digest:
        # the digest covers matchId/winner/times/deadline/chain/contract.)
        "forfeits": record.get("forfeits", {}),
    }
