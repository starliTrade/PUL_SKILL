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
# ORACLE_CHAIN_ID once; on mismatch every subsequent read FAILS CLOSED
# (returns None → rounds refused) instead of trusting cross-chain data.
_chain_id_checked = False
_chain_id_mismatch = False


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

_cache: dict[str, tuple[bool, float]] = {}


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


def duel_status(match_id: str, *, use_cache: bool = True) -> int | None:
    """On-chain DuelMatch.status for this match id, or None if unknown.

    Never raises: every failure mode (bad id, dead RPC, bad payload, chain
    mismatch) returns None, which the deposit gate turns into fail-closed
    409 — never a 500.
    """
    global _chain_id_checked, _chain_id_mismatch
    if not escrow_configured():
        return None
    if not _chain_id_checked:
        observed = _rpc_chain_id()
        if observed is not None:
            _chain_id_checked = True
            expected_raw = os.environ.get("ORACLE_CHAIN_ID", "80002")
            if observed != int(expected_raw):
                _chain_id_mismatch = True
    if _chain_id_mismatch:
        return None  # fail-closed: never trust reads from the wrong chain
    try:
        key = _match_id_to_bytes32(match_id)
    except Exception:
        return None
    if use_cache:
        cached = _cache.get(key)
        if cached and time.time() < cached[1]:
            return STATUS_ACTIVE if cached[0] else None
    try:
        status = _decode_status(_eth_call(os.environ["ESCROW_ADDRESS"], _matches_selector() + key[2:]))
    except Exception:
        status = None
    if use_cache:
        verified = status == STATUS_ACTIVE
        ttl = _POSITIVE_TTL if verified else _NEGATIVE_TTL
        _cache[key] = (verified, time.time() + ttl)
    return status


def deposits_verified(match_id: str) -> bool:
    """True when the escrow reports BOTH stakes locked (duel Active)."""
    return duel_status(match_id) == STATUS_ACTIVE
