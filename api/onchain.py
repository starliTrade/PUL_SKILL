"""
PULSAR — On-chain deposit verification (audit #5, item 1).

The server previously trusted clients to deposit before playing: a custom
client could matchmake, never stake, and grief an honest opponent whose own
deposit was then locked until the 30-minute refund horizon. This module makes
the server INDEPENDENTLY verify, via read-only eth_call, that the escrow holds
both stakes (duel status == Active) before any round commit is accepted.

Design notes:
- Plain JSON-RPC over urllib — no new dependency (web3 is not in requirements).
- Fail-CLOSED: if the RPC is unreachable while escrow mode is configured, the
  commit is refused. Money is involved; refusing beats trusting.
- Short-TTL caches keep the 3-round flow to ~1 RPC per player.
- When escrow mode is NOT configured (no ESCROW_ADDRESS / RPC), the gate is
  inactive — practice and unconfigured dev environments keep working.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any

# DuelMatch.status (contracts/PulsarEscrow.sol): None=0 Created=1 Active=2
# Settled=3 Cancelled=4 Refunded=5. Both stakes are locked exactly when the
# duel is Active; Created means only the creator's stake is in.
STATUS_NONE = 0
STATUS_CREATED = 1
STATUS_ACTIVE = 2

RPC_TIMEOUT_SECONDS = 5.0
_POSITIVE_TTL = 60.0   # verified-deposit cache (both stakes seen)
_NEGATIVE_TTL = 10.0   # unverified cache (retry RPC quickly but not per call)

# Audit #7 — chain-binding cross-check. Three env vars describe one chain
# (ESCROW_RPC_URL's network, ORACLE_CHAIN_ID for signatures, VITE_CHAIN_ID in
# the client). A mismatch would let the gate "verify" deposits on a network
# where the client's duels do not exist. The RPC's eth_chainId is compared to
# ORACLE_CHAIN_ID; on mismatch every read FAILS CLOSED (returns None → rounds
# refused). Audit #8 F-16: the latch is no longer permanent — it re-checks
# after a cooldown so a transient RPC hiccup doesn't wedge the service until
# a manual restart.
_chain_id_checked = False
_chain_id_mismatch = False
_CHAIN_MISMATCH_COOLDOWN = 60.0
_chain_mismatch_until = 0.0


def _rpc_chain_id() -> int | None:
    """eth_chainId of the configured RPC, or None when it cannot be read."""
    try:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}
        ).encode("utf-8")
        req = urllib.request.Request(
            os.environ["ESCROW_RPC_URL"],
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=RPC_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return int(str(body.get("result")), 16)
    except Exception:
        return None

_cache: dict[str, tuple[Any, ...]] = {}  # key -> (status|None, expiry, info)

# Audit #8 F-03: payment-token decimals, cached once (None = unreadable → the
# stake comparison fails closed instead of guessing 6 decimals and silently
# comparing 10^k-scaled numbers).
_token_decimals: int | None | str = "unread"


def token_decimals() -> int | None:
    """decimals() of the escrow's payment token, read once and cached.

    Audit #8 F-03/F-18: a wrong decimals assumption scales every stake
    comparison by 10^k — read the token from the escrow's paymentToken()
    view, then read its decimals(). Fail-closed (None) when unreadable."""
    global _token_decimals
    if not escrow_configured():
        return None
    if _token_decimals != "unread":
        return _token_decimals  # type: ignore[return-value]
    try:
        token = _escrow_token_address()
        if token is None:
            _token_decimals = None
            return None
        ret = _eth_call(token, _selector("decimals()"))
        if ret is None:
            _token_decimals = None
            return None
        _token_decimals = int(ret[-64:], 16)
    except Exception:
        _token_decimals = None
    return _token_decimals  # type: ignore[return-value]


def _escrow_token_address() -> str | None:
    """paymentToken() of the escrow (static call), or None."""
    try:
        ret = _eth_call(os.environ["ESCROW_ADDRESS"], _selector("paymentToken()"))
        if ret is None or len(ret) < 66:
            return None
        return "0x" + ret[-40:]
    except Exception:
        return None


def escrow_configured() -> bool:
    """True when the server has both a contract and an RPC to read it."""
    return bool(os.environ.get("ESCROW_ADDRESS")) and bool(os.environ.get("ESCROW_RPC_URL"))


def _match_id_to_bytes32(match_id: str) -> str:
    """The bytes32 key the escrow contract stores duels under.

    Audit #6 C1: this MUST match the client (gameServerClient.matchIdToBytes32)
    and the oracle (oracle._match_id_bytes32) byte-for-byte. All three now use
    the SAME convention — sha256 of the raw server id — so the gate reads the
    duel that actually exists on-chain. The previous raw-32-hex requirement
    raised ValueError outside the fail-closed handler on EVERY production
    round action (server ids are 32 chars, not 64) and would have queried the
    wrong key even if it had not crashed.
    """
    import hashlib

    clean = match_id.lower().removeprefix("0x")
    if len(clean) == 64 and all(c in "0123456789abcdef" for c in clean):
        return "0x" + clean  # already a bytes32 id (used by tests)
    return "0x" + hashlib.sha256(match_id.encode("utf-8")).hexdigest()


def _keccak(data: bytes) -> bytes:
    from Crypto.Hash import keccak as _k

    h = _k.new(digest_bits=256)
    h.update(data)
    return h.digest()


def _matches_selector() -> str:
    return "0x" + _keccak(b"matches(bytes32)")[:4].hex()


def _selector(sig: str) -> str:
    """ABI selector for a function signature, computed at runtime (no
    hand-copied constants that can drift)."""
    return "0x" + _keccak(sig.encode())[:4].hex()


def _decode_status(ret: str) -> int | None:
    """Decode the uint8 status word from the matches(bytes32) return data.

    DuelMatch is an all-static struct: the return payload is 10 words, and
    `status` is member index 6 (after matchId, player1, player2, stakeAmount,
    totalPool, createdAt).
    """
    data = ret.removeprefix("0x")
    if len(data) < (6 + 1) * 64:
        return None
    try:
        return int(data[6 * 64 : 7 * 64], 16)
    except ValueError:
        return None


def _eth_call(to: str, data: str) -> str | None:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        os.environ["ESCROW_RPC_URL"],
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=RPC_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    result = body.get("result") if isinstance(body, dict) else None
    if body.get("error") or not isinstance(result, str) or result in ("0x", ""):
        return None
    return result


def _chain_ok() -> bool:
    """Chain-binding cross-check with a cooldown (audit #8 F-16).

    On a mismatch the service fails closed, but the latch now EXPIRES so a
    transient wrong answer from an RPC (or a reconfigured env) recovers
    itself instead of wedging until a manual restart."""
    global _chain_id_checked, _chain_id_mismatch, _chain_mismatch_until
    if not escrow_configured():
        return False
    now = time.time()
    if _chain_id_mismatch and now < _chain_mismatch_until:
        return False
    if _chain_id_mismatch and now >= _chain_mismatch_until:
        _chain_id_checked = False  # cooldown expired — re-observe
        _chain_id_mismatch = False
    if not _chain_id_checked:
        observed = _rpc_chain_id()
        if observed is not None:
            _chain_id_checked = True
            expected_raw = os.environ.get("ORACLE_CHAIN_ID", "80002")
            if observed != int(expected_raw):
                _chain_id_mismatch = True
                _chain_mismatch_until = now + _CHAIN_MISMATCH_COOLDOWN
    return not _chain_id_mismatch


def duel_info(match_id: str, *, use_cache: bool = True) -> dict[str, Any] | None:
    """Full on-chain DuelMatch state, or None when unreadable.

    Audit #8 F-03: the gate can no longer be fooled by a duel whose STATUS is
    Active but whose stake or participants differ from the server's match.
    Returns {status, player1, player2, stakeAmount, totalPool} — the raw
    uint256 stake (token units; convert via token_decimals()).

    Never raises: every failure mode (bad id, dead RPC, bad payload, chain
    mismatch) returns None, which the deposit gate turns into fail-closed
    409 — never a 500.
    """
    if not _chain_ok():
        return None
    try:
        key = _match_id_to_bytes32(match_id)
    except Exception:
        return None
    if use_cache:
        cached = _cache.get(key)
        if cached and time.time() < cached[1]:
            info = cached[2] if len(cached) > 2 else None
            return info
    try:
        ret = _eth_call(os.environ["ESCROW_ADDRESS"], _matches_selector() + key[2:])
    except Exception:
        ret = None
    info = _decode_match(ret)
    if use_cache:
        status = info.get("status") if info else None
        verified = status == STATUS_ACTIVE
        ttl = _POSITIVE_TTL if verified else _NEGATIVE_TTL
        _cache[key] = (status, time.time() + ttl, info)
    return info


def _decode_match(ret: str | None) -> dict[str, Any] | None:
    """Decode the 10-word static DuelMatch struct from matches(bytes32)."""
    if not ret:
        return None
    data = ret.removeprefix("0x")
    if len(data) < 10 * 64:
        return None
    try:
        words = [int(data[i * 64 : (i + 1) * 64], 16) for i in range(10)]
    except ValueError:
        return None
    return {
        "player1": "0x" + f"{words[1] & ((1 << 160) - 1):040x}",
        "player2": "0x" + f"{words[2] & ((1 << 160) - 1):040x}",
        "stakeAmount": words[3],
        "totalPool": words[4],
        "createdAt": words[5],
        "status": words[6],
        "winner": "0x" + f"{words[7] & ((1 << 160) - 1):040x}",
    }


def duel_status(match_id: str, *, use_cache: bool = True) -> int | None:
    """On-chain DuelMatch.status for this match id, or None if unknown."""
    info = duel_info(match_id, use_cache=use_cache)
    return info.get("status") if info else None


def deposits_verified(match_id: str) -> bool:
    """True when the escrow reports BOTH stakes locked (duel Active)."""
    return duel_status(match_id) == STATUS_ACTIVE


def verify_deposit(
    info: dict[str, Any] | None,
    agreed_stake: float,
    server_players: list[str] | set[str],
    decimals: int | None = None,
) -> bool:
    """Audit #8 F-03 — validate a decoded duel against the server's match.

    The old gate only checked status == Active, which accepted a duel with a
    dust stake (creator locks the pot at 0.000001 USDT while the UI promises
    the full prize) or wrong participants (deposited from wallet W2, playing
    as W1 → the contract's participant check makes the winner unpayable and
    both stakes burn 30 minutes).

    Accepts only: status == Active AND stakeAmount == agreed stake in token
    units AND {player1, player2} == the server's two participants.
    """
    if not info:
        return False
    if info.get("status") != STATUS_ACTIVE:
        return False
    if decimals is None:
        decimals = token_decimals()
    if decimals is None:
        return False  # cannot verify the amount — fail-closed
    expected_units = int(round(float(agreed_stake) * (10**int(decimals))))
    if int(info.get("stakeAmount", 0)) != expected_units:
        return False
    onchain_players = {
        str(info.get("player1", "")).lower(),
        str(info.get("player2", "")).lower(),
    }
    server_set = {p.lower() for p in server_players}
    if len(server_set) != 2 or onchain_players != server_set:
        return False
    return True


# --- Settlement-claim verification (audit #8 F-04) ---------------------------

def _tx_receipt(tx_hash: str) -> dict[str, Any] | None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            os.environ["ESCROW_RPC_URL"],
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=RPC_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result = body.get("result")
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def verify_settlement_tx(tx_hash: str, match_id: str, claimer: str) -> bool:
    """Audit #8 F-04: a claimed settlement tx must REALLY settle THIS match.

    Verifies, straight from the RPC:
      - the receipt exists and succeeded (status == 0x1)
      - the tx targeted the configured ESCROW_ADDRESS
      - its logs contain MatchSettled(matchId, winner, ...) with the bytes32
        key derived from THIS server match id and winner == claimer
    Without all of that the "on-chain proof" would be user-supplied fiction.
    """
    if not escrow_configured() or not _chain_ok():
        return False
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash or ""):
        return False
    receipt = _tx_receipt(tx_hash)
    if not receipt or str(receipt.get("status", "")).lower() not in ("0x1", "1"):
        return False
    if str(receipt.get("to", "")).lower() != os.environ.get("ESCROW_ADDRESS", "").lower():
        return False
    try:
        key32 = _match_id_to_bytes32(match_id)
    except Exception:
        return False
    event_topic = "0x" + _keccak(
        b"MatchSettled(bytes32,address,uint256,uint256)"
    ).hex()
    claimer_topic = "0x" + claimer.lower().removeprefix("0x").rjust(64, "0")
    for log in receipt.get("logs") or []:
        if str(log.get("address", "")).lower() != os.environ.get("ESCROW_ADDRESS", "").lower():
            continue
        topics = log.get("topics") or []
        if len(topics) >= 3 and topics[0] == event_topic and topics[1] == key32 and topics[2] == claimer_topic:
            return True
    return False
