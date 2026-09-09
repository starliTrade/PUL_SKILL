"""
PULSAR P1.14 — Referee Oracle signing service.

Design (P1.14):
- The oracle private key NEVER touches application memory of web workers:
  this module reads it from ORACLE_PRIVATE_KEY (in production, swap the
  loader for AWS KMS / GCP KMS — the signing surface stays identical).
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
import time
from typing import Any

from eth_account import Account

# EIP-191 personal-message prefix the contract applies before ecrecover.
_EIP191_PREFIX = b"\x19Ethereum Signed Message:\n32"

# Deadline for on-chain submission of a signed settlement.
SETTLEMENT_DEADLINE_SECONDS = 600  # 10 minutes

_KMS_KEY_ENV = "ORACLE_PRIVATE_KEY"
_DEFAULT_CHAIN_ID = 137


def _load_signer() -> Account:
    key = os.environ.get(_KMS_KEY_ENV, "")
    if not key:
        raise RuntimeError(
            f"{_KMS_KEY_ENV} is required for the referee oracle. In production, "
            "provide it via KMS and adapt _load_signer() accordingly."
        )
    return Account.from_key(key if key.startswith("0x") else f"0x{key}")


def oracle_address() -> str:
    return _load_signer().address


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
    if s > _SECP256K1_HALF_N:
        s = _SECP256K1_N - s
        v ^= 0x01  # flips 27<->28 and 0<->1 alike
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


def _address_bytes32(address: str) -> bytes:
    clean = address.lower().removeprefix("0x")
    if len(clean) != 40:
        raise ValueError(f"bad address: {address}")
    return bytes.fromhex(clean).rjust(32, b"\x00")


def _match_id_bytes32(match_id: str) -> bytes:
    clean = match_id.lower().removeprefix("0x")
    if len(clean) == 64:
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

    packed = b"".join(
        [
            _match_id_bytes32(str(record["matchId"])),
            _address_bytes32(str(record["winner"])),
            _uint256(int(record["winnerTimeMs"])),
            _uint256(int(record["loserTimeMs"])),
            _uint256(int(server_nonce)),
            _uint256(int(record["deadline"])),
            _uint256(int(chain_id)),
            _address_bytes32(escrow_address),
        ]
    )
    inner = _keccak(packed)
    return _keccak(_EIP191_PREFIX + inner)


def sign_settlement(record: dict[str, Any]) -> dict[str, Any]:
    """
    Sign one engine-produced settlement. The record MUST come from
    match_engine.settle(), not from client input.
    """
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
    deadline = int(time.time()) + SETTLEMENT_DEADLINE_SECONDS

    digest = build_settlement_digest(
        {
            "matchId": record["matchId"],
            "winner": record["winner"],
            "winnerTimeMs": record["winnerTimeMs"],
            "loserTimeMs": record["loserTimeMs"],
            "deadline": deadline,
        },
        server_nonce,
    )
    signed = _sign_hash_bytes(_load_signer(), digest)
    raw_sig = bytes(signed.signature) if not isinstance(signed.signature, bytes) else signed.signature
    low_s = _signature_to_low_s_bytes(raw_sig)
    signature = "0x" + low_s.hex()

    return {
        "matchId": record["matchId"],
        "winner": record["winner"],
        "winnerTimeMs": record["winnerTimeMs"],
        "loserTimeMs": record["loserTimeMs"],
        "serverNonce": server_nonce,
        "deadline": deadline,
        "oracleAddress": _load_signer().address,
        "signature": signature,
        "validatedTimes": record.get("validatedTimes", {}),
    }
