"""
PULSAR — On-chain deposit verification (audit #5, item 1).

The server previously trusted clients to deposit before playing: a custom
client could matchmake, never stake, and grief an honest opponent whose own
deposit was then locked until the refund horizon. This module makes
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

import enum
import json
import os
import re
import time
import urllib.request
from typing import Any

import timebase

# DuelMatch.status (contracts/PulsarEscrow.sol): None=0 Created=1 Active=2
# Settled=3 Cancelled=4 Refunded=5. Both stakes are locked exactly when the
# duel is Active; Created means only the creator's stake is in.
STATUS_NONE = 0
STATUS_CREATED = 1
STATUS_ACTIVE = 2

RPC_TIMEOUT_SECONDS = 5.0
# A VERIFIED deposit is immutable for the life of the duel, so caching it is
# free correctness.
_POSITIVE_TTL = 60.0
# An UNVERIFIED read is a TRANSIENT state, not a fact: the client deposits
# on-chain right after the match is created, so "not verified yet" is expected
# for a few seconds and then becomes false. Caching it for 10s (audit
# 2026-10-14, found by the phase-10 ranked E2E) meant a gate read that happened
# BEFORE the deposit kept answering "not verified" AFTER it — and the player's
# first round was refused with
# `409 "On-chain deposits are not verified for this match yet."`
#
# That is also what made the browser E2E look flaky: the same flow passed or
# failed depending on whether the negative window had expired. The bug was
# never the driver. Do not cache a negative.
_NEGATIVE_TTL = 0.0

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

# Audit M15: the cache was never evicted — only expiry-CHECKED on read — so it
# grew by one entry per match id ever queried. On a long-running server that is
# an unbounded leak. Entries are now dropped once the map passes this size,
# expired ones first.
_CACHE_MAX_ENTRIES = 2048


def _cache_store(key: str, entry: tuple[Any, ...]) -> None:
    """Insert into the on-chain read cache, keeping it bounded (audit M15)."""
    _cache[key] = entry
    if len(_cache) <= _CACHE_MAX_ENTRIES:
        return
    now = timebase.now()
    for stale in [k for k, v in _cache.items() if v[1] <= now]:
        _cache.pop(stale, None)
    overflow = len(_cache) - _CACHE_MAX_ENTRIES
    if overflow > 0:
        # Everything left is still fresh: drop the soonest-to-expire entries.
        for oldest, _ in sorted(_cache.items(), key=lambda kv: kv[1][1])[:overflow]:
            _cache.pop(oldest, None)

# Audit #8 F-03: payment-token decimals, cached once (None = unreadable → the
# stake comparison fails closed instead of guessing 6 decimals and silently
# comparing 10^k-scaled numbers).
_token_decimals: int | None | str = "unread"
# Audit C2: a FAILED read used to be cached as None for the life of the
# process. One 5-second RPC blip therefore made every later ACTIVE duel fail
# `verify_deposit`, and the gate turned that into `status = "void"` — the
# legitimate winner was never paid, unrecoverably, until a restart. A failure
# is now cached only briefly (so an outage does not hammer the RPC on every
# round action) while a SUCCESS is cached forever (decimals are immutable).
_TOKEN_DECIMALS_RETRY_SECONDS = 10.0
_token_decimals_retry_after = 0.0
# ERC-20 `decimals()` is a uint8, so anything above 255 is a broken or hostile
# token, not a scale factor. Without this bound `deposit_verdict` computed
# `Decimal(10) ** <garbage>` and raised decimal.Overflow — an unhandled 500 on
# the money path instead of a fail-closed refusal.
_MAX_TOKEN_DECIMALS = 255


def token_decimals() -> int | None:
    """decimals() of the escrow's payment token, or None when unreadable.

    Audit #8 F-03/F-18: a wrong decimals assumption scales every stake
    comparison by 10^k — read the token from the escrow's paymentToken()
    view, then read its decimals(). Fail-closed (None) when unreadable.

    None means "could not read", never "zero" and never "mismatch" — callers
    that must act on the difference should use `deposit_verdict()`.
    """
    global _token_decimals, _token_decimals_retry_after
    if not escrow_configured():
        return None
    if _token_decimals != "unread":
        if isinstance(_token_decimals, int):
            return _token_decimals  # immutable once read — cache for the process
        if timebase.now() < _token_decimals_retry_after:
            return None  # a recent failure; do not hammer the RPC
        # The failure cache has expired — fall through and retry.
    try:
        token = _escrow_token_address()
        ret = _eth_call(token, _selector("decimals()")) if token else None
        if ret is None:
            raise ValueError("decimals() unreadable")
        value = int(ret[-64:], 16)
        if not 0 <= value <= _MAX_TOKEN_DECIMALS:
            raise ValueError(f"decimals() out of range: {value}")
    except Exception:
        _token_decimals = None
        _token_decimals_retry_after = timebase.now() + _TOKEN_DECIMALS_RETRY_SECONDS
        return None
    _token_decimals = value
    _token_decimals_retry_after = 0.0
    return value


# Audit M-11: the escrow the server talks to must be the escrow it was written
# for. Before this the server accepted ANY address at ESCROW_ADDRESS: after a
# redeploy, a stale value in one environment looked like "configured and
# healthy" while every settlement hit old code, and a typo pointed at a random
# contract that happened to answer `matches(bytes32)` with zeros.
#
# Bumped together with `PulsarEscrow.VERSION_CODE`. `tests/unit/test_contract_version.py`
# fails if the two ever disagree, and if the version is not documented in
# `docs/UPGRADE-PATH.md`.
EXPECTED_ESCROW_VERSION = 2
EXPECTED_ESCROW_VERSION_NAME = "2.0.0"

_escrow_version_cache: dict[str, Any] | None = None
# The last answer that was actually COMPUTED, kept through the retry cooldown so
# /api/health does not flip between "incompatible" and "unreadable" every minute.
_escrow_version_last: dict[str, Any] | None = None
_escrow_version_retry_after = 0.0
_ESCROW_VERSION_RETRY_SECONDS = 60.0


def escrow_version() -> dict[str, Any] | None:
    """`VERSION()` / `VERSION_CODE()` of the configured escrow.

    Returns None when there is no escrow configured or the read failed, and a
    dict {"code": int|None, "name": str|None, "expected": int, "compatible":
    bool} otherwise. `compatible` is False for an escrow that answers with no
    version at all (a pre-2.0 deployment), which is the case that matters: it
    is running code this server was not written against.
    """
    global _escrow_version_cache, _escrow_version_last, _escrow_version_retry_after
    if not escrow_configured():
        return None
    if _escrow_version_cache is not None:
        return dict(_escrow_version_cache)
    if timebase.now() < _escrow_version_retry_after and _escrow_version_last is not None:
        return dict(_escrow_version_last)
    escrow = os.environ["ESCROW_ADDRESS"]
    # Each read is independent: one failing call must not discard the other's
    # answer, and a transient error on the first must not make the server report
    # "this contract publishes no version" for a contract that does.
    code: int | None = None
    name: str | None = None
    try:
        code_word = _eth_call(escrow, _selector("VERSION_CODE()"))
        code = int(code_word[-64:], 16) if code_word else None
    except Exception:
        code = None
    try:
        name = _decode_string(_eth_call(escrow, _selector("VERSION()")))
    except Exception:
        name = None
    if code is None and name is None:
        # Unreadable, or (worse) an escrow old enough not to publish a version.
        # Do not cache a transient RPC failure for the life of the process; a
        # genuinely old contract keeps answering the same way, so a 60 s window
        # is enough for the operator to see it in /api/health.
        _escrow_version_retry_after = timebase.now() + _ESCROW_VERSION_RETRY_SECONDS
        _escrow_version_last = {
            "code": None,
            "name": None,
            "expected": EXPECTED_ESCROW_VERSION,
            "compatible": False,
        }
        return dict(_escrow_version_last)
    version = {
        "code": code,
        "name": name,
        "expected": EXPECTED_ESCROW_VERSION,
        "compatible": code == EXPECTED_ESCROW_VERSION,
    }
    _escrow_version_cache = dict(version)  # immutable for an address — cache forever
    _escrow_version_last = dict(version)
    return version


def _decode_string(ret: str | None) -> str | None:
    """Decode a dynamic ABI `string` return value, or None."""
    if not ret:
        return None
    data = ret.removeprefix("0x")
    try:
        offset = int(data[0:64], 16) * 2
        length = int(data[offset : offset + 64], 16) * 2
        raw = data[offset + 64 : offset + 64 + length]
        value = bytes.fromhex(raw).decode("utf-8")
    except Exception:
        return None
    # Only printable, sane-length strings: a hostile contract must not be able
    # to push megabytes of junk into the health payload.
    if not value or len(value) > 32 or not value.isprintable():
        return None
    return value


def escrow_version_problem() -> str | None:
    """A one-line reason the configured escrow is not the expected one.

    None means "fine" or "not configured" — callers decide whether an
    unconfigured chain is fatal for them.
    """
    if not escrow_configured():
        return None
    version = escrow_version()
    if version is None:
        return "escrow version unreadable"
    if version["compatible"]:
        return None
    if version["code"] is None:
        return f"escrow does not publish VERSION(); server expects {EXPECTED_ESCROW_VERSION_NAME}"
    return (
        f"escrow VERSION_CODE={version['code']} but the server expects "
        f"{EXPECTED_ESCROW_VERSION} ({EXPECTED_ESCROW_VERSION_NAME})"
    )


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


# The reachability probe's own cooldown. `_chain_ok` latches after the FIRST
# successful chain-id read, so it cannot answer "is the RPC up right now".
_RPC_PROBE_COOLDOWN = 5.0
_rpc_reachable_cache: bool | None = None
_rpc_probed_at = 0.0


# The chain clock is cached for a few seconds.
#
# Audit 2026-10-16 (HIGH): reading it live put up to ~15s of blocking network I/O
# inside the store's transaction — the exact H10 bug class that was fixed for the
# deposit gate and reintroduced here. In memory mode one slow RPC stalls every
# match in the process; on Firestore it holds a transaction open across socket
# I/O. If signing keeps failing, the refund window opens and the WINNER loses
# their prize.
#
# A few seconds of staleness is free: the deadline is a 10-minute window.
_CHAIN_NOW_TTL_SECONDS = 5.0
# (rpc url it was read from, monotonic stamp, chain time).
# NOT a `timebase.now()` stamp: see `chain_now`.
_chain_now_cache: tuple[str, float, int] | None = None


def reset_escrow_version_cache() -> None:
    """Forget the cached escrow version (tests, and after an operator redeploy)."""
    global _escrow_version_cache, _escrow_version_last, _escrow_version_retry_after
    _escrow_version_cache = None
    _escrow_version_last = None
    _escrow_version_retry_after = 0.0


def reset_chain_now_cache() -> None:
    """Forget the cached chain clock. Tests and the drill call this."""
    global _chain_now_cache
    _chain_now_cache = None


def chain_now() -> int | None:
    """The CHAIN's current time, or None when it cannot be read.

    Cached for `_CHAIN_NOW_TTL_SECONDS` so the signing path — which runs inside
    the store's transaction — does not perform blocking I/O on every call.

    Audit 2026-10-15 (found by a time-travel test, recorded as an open item):
    the settlement deadline was computed from the SERVER's clock while the
    contract enforces `block.timestamp <= proof.deadline` on the CHAIN's. A drift
    larger than the deadline window makes every proof arrive already expired —
    settlement becomes impossible and the winner can only wait for the refund.

    The fix is to stop guessing which clock the contract will use: ask it.
    """
    global _chain_now_cache
    # The TTL is measured on `time.monotonic()`, NOT on `timebase.now()`.
    #
    # Audit 2026-10-24, and it cost a red chain gate to find: the first version
    # stamped the cache with `timebase.now()` — the app's business clock, which
    # tests and the time-travel drill MOVE. A test that advances the clock by two
    # hours and then calls `chain_now()` writes a stamp two hours in the FUTURE;
    # when the clock is restored, `now - stamp` is negative and therefore "fresh"
    # for the next two real hours. The cached value then outlives the anvil it was
    # read from, `oracle.sign_settlement` mints `deadline = stale_chain_time + 600`,
    # and every proof arrives already expired — settlement impossible, the winner
    # forced onto the refund path, which is exactly the failure this function was
    # added to prevent (see the docstring above).
    #
    # A wall clock is not allowed to decide how long a cache stays valid: NTP
    # steps and operator time changes do the same thing in production. Monotonic
    # time cannot go backwards or jump.
    now = time.monotonic()
    # The URL is part of the key. `test_chain_now_returns_none_...` used to need a
    # manual `reset_chain_now_cache()` after changing ESCROW_RPC_URL, with a
    # comment explaining that otherwise it "reads the previous chain's value" —
    # a manual step every future caller would have to remember. Two chains do not
    # share a clock, so a cached value must never cross an endpoint change.
    url = os.environ.get("ESCROW_RPC_URL", "")
    cache = _chain_now_cache
    if (
        cache is not None
        and cache[0] == url
        and now - cache[1] < _CHAIN_NOW_TTL_SECONDS
    ):
        return cache[2]
    try:
        out = _rpc_call("eth_getBlockByNumber", ["latest", False])
        result = (out or {}).get("result") or {}
        stamp = result.get("timestamp")
        if not isinstance(stamp, str):
            return None
        value = int(stamp, 16)
        _chain_now_cache = (url, now, value)
        return value
    except Exception:  # noqa: BLE001
        return None


def duel_activated_at(match_id: str) -> int | None:
    """The escrow's `activatedAt[matchId]`, or None.

    The contract's own clock origin for the play window (audit H20). Reading it
    means the server's clamp cannot disagree with the contract's.
    """
    try:
        key = _match_id_to_bytes32(match_id)
    except Exception:  # noqa: BLE001
        return None
    try:
        ret = _eth_call(os.environ["ESCROW_ADDRESS"], _activated_at_selector() + key[2:])
    except Exception:  # noqa: BLE001
        return None
    if not ret or len(ret) < 66:
        return None
    try:
        return int(ret, 16)
    except ValueError:
        return None


# NOTE (2026-10-16): a `duel_created_at` reader was added here and then removed.
# The contract computes `clockOrigin = max(activatedAt, createdAt)`, and I read
# that as meaning createdAt can exceed activatedAt. It cannot: `joinDuel` sets
# `activatedAt = block.timestamp` strictly after `createDuel` set `createdAt`
# (PulsarEscrow.sol:337, 367), so `activatedAt >= createdAt` always and the max()
# is always activatedAt. The extra eth_call was ~5s of blocking I/O inside the
# store transaction for a branch that cannot occur. The mirror is exact without
# it; the comment that claimed otherwise was wrong and is corrected in oracle.py.

def _activated_at_selector() -> str:
    return _selector("activatedAt(bytes32)")


def _rpc_call(method: str, params: list) -> dict | None:
    """A raw JSON-RPC call. Returns None on any failure — never raises."""
    import json as _json
    import urllib.request as _url

    url = os.environ.get("ESCROW_RPC_URL", "")
    if not url:
        return None
    try:
        req = _url.Request(
            url,
            data=_json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with _url.urlopen(req, timeout=RPC_TIMEOUT_SECONDS) as res:
            return _json.loads(res.read() or b"{}")
    except Exception:  # noqa: BLE001
        return None


def _rpc_reachable() -> bool:
    """Whether the configured RPC answered recently (cooldown-cached).

    Audit 2026-10-13 (found by the phase-10 chaos suite): `chain_reachable()`
    returned `_chain_ok()`, which only reports a chain-id MISMATCH. With the
    node down, `_rpc_chain_id()` returns None, the mismatch latch never trips,
    and `/api/health` reported `rpc.reachable: true` **while the RPC was dead** —
    a health probe that lies is worse than no probe, because an operator trusts
    it. The deposit gate was never fooled (it does the real call and fails
    closed), but the signal an operator reads was.
    """
    global _rpc_reachable_cache, _rpc_probed_at
    if not escrow_configured():
        return False
    now = timebase.now()
    if _rpc_reachable_cache is not None and now - _rpc_probed_at < _RPC_PROBE_COOLDOWN:
        return _rpc_reachable_cache
    _rpc_reachable_cache = _rpc_chain_id() is not None
    _rpc_probed_at = now
    return _rpc_reachable_cache


def chain_reachable() -> bool:
    """Public wrapper for /api/health (phase 6.2).

    Answers "is the RPC answering", not "does its chain id match" — those are
    different questions and the health endpoint needs the first one.
    """
    return _rpc_reachable()


def rpc_chain_id() -> int | None:
    """The chain id the configured RPC reports, or None (phase 6.2)."""
    return _rpc_chain_id()


def _chain_ok() -> bool:
    """Chain-binding cross-check with a cooldown (audit #8 F-16).

    On a mismatch the service fails closed, but the latch now EXPIRES so a
    transient wrong answer from an RPC (or a reconfigured env) recovers
    itself instead of wedging until a manual restart."""
    global _chain_id_checked, _chain_id_mismatch, _chain_mismatch_until
    if not escrow_configured():
        return False
    now = timebase.now()
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
        if cached and timebase.now() < cached[1]:
            info = cached[2] if len(cached) > 2 else None
            return info
    try:
        ret = _eth_call(os.environ["ESCROW_ADDRESS"], _matches_selector() + key[2:])
    except Exception:
        ret = None
    info = _decode_match(ret)
    if use_cache:
        status = info.get("status") if info else None
        if status == STATUS_ACTIVE:
            # Verified: both stakes are locked and cannot un-lock. Cache it.
            _cache_store(key, (status, timebase.now() + _POSITIVE_TTL, info))
        # NOT verified: deliberately NOT cached — see _NEGATIVE_TTL. The client
        # may be mid-deposit, and a stale negative refuses a legitimate round.
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


class DepositVerdict(enum.Enum):
    """Audit C2 — three outcomes, because two of them need different actions.

    The gate used to collapse "cannot read the chain" and "the chain says this
    is a different duel" into a single False, and the caller turned BOTH into
    `match.status = "void"`. A transient RPC failure therefore destroyed a live
    match and cost the winner their prize. They are not the same thing:
    """

    MATCH = "match"        # provably THIS match, both stakes locked → play on
    MISMATCH = "mismatch"  # readable, but wrong stake/participants → void
    UNKNOWN = "unknown"    # cannot read → refuse the round, do NOT void


def deposit_verdict(
    info: dict[str, Any] | None,
    agreed_stake: float,
    server_players: list[str] | set[str],
    decimals: int | None = None,
) -> DepositVerdict:
    """Audit #8 F-03 — validate a decoded duel against the server's match.

    The old gate only checked status == Active, which accepted a duel with a
    dust stake (creator locks the pot at 0.000001 USDT while the UI promises
    the full prize) or wrong participants (deposited from wallet W2, playing
    as W1 → the contract's participant check makes the winner unpayable and
    both stakes burn until the refund horizon).

    MATCH requires ALL of: status == Active, stakeAmount == the agreed stake in
    token units, and {player1, player2} == the server's two participants.
    """
    if not info:
        return DepositVerdict.UNKNOWN
    if info.get("status") != STATUS_ACTIVE:
        # A readable duel that is not Active is a real mismatch (Created,
        # Settled, Refunded, Cancelled) — the caller may void on this.
        return DepositVerdict.MISMATCH
    if decimals is None:
        decimals = token_decimals()
    if decimals is None:
        # Cannot scale the stake, so the amount is unverifiable. NOT a mismatch.
        return DepositVerdict.UNKNOWN
    # P0-fix: Decimal (not float) so large/fractional stakes never lose a unit
    # to binary rounding and brick an honest Active duel.
    import decimal
    from decimal import Decimal, InvalidOperation

    try:
        expected_units = int(
            (Decimal(str(agreed_stake)) * (Decimal(10) ** int(decimals))).to_integral_value()
        )
    except (InvalidOperation, ValueError, OverflowError, decimal.Overflow):
        return DepositVerdict.UNKNOWN
    if int(info.get("stakeAmount", 0)) != expected_units:
        return DepositVerdict.MISMATCH
    onchain_players = {
        str(info.get("player1", "")).lower(),
        str(info.get("player2", "")).lower(),
    }
    server_set = {p.lower() for p in server_players}
    if len(server_set) != 2 or onchain_players != server_set:
        return DepositVerdict.MISMATCH
    return DepositVerdict.MATCH


def verify_deposit(
    info: dict[str, Any] | None,
    agreed_stake: float,
    server_players: list[str] | set[str],
    decimals: int | None = None,
) -> bool:
    """Boolean view of `deposit_verdict`: True only for a provable MATCH.

    Kept for callers that genuinely only need "may this duel proceed?" — the
    audit probes and the settlement path. UNKNOWN is NOT a match (fail-closed),
    but callers that must distinguish it from a mismatch should call
    `deposit_verdict` directly.
    """
    return (
        deposit_verdict(info, agreed_stake, server_players, decimals) is DepositVerdict.MATCH
    )


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
        # Audit H-26: `logs` comes from an RPC response, not from us. A malformed
        # entry (a string, a null, a provider quirk) used to raise AttributeError
        # here — inside the CLAIM endpoint, which then answered 500 to a player
        # whose prize was already on chain. "Never raise" is part of the contract
        # of a verifier that must fail CLOSED.
        if not isinstance(log, dict):
            continue
        if str(log.get("address", "")).lower() != os.environ.get("ESCROW_ADDRESS", "").lower():
            continue
        topics = log.get("topics") or []
        if len(topics) >= 3 and topics[0] == event_topic and topics[1] == key32 and topics[2] == claimer_topic:
            return True
    return False
