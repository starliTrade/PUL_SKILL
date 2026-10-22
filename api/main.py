"""
PULSAR P1.11/P2.2a — Authoritative game server (FastAPI).

Endpoints:
  GET  /api/health
  POST /api/auth/nonce            {address}              -> {nonce, message}
  POST /api/auth/verify           {message, signature}   -> {token}
  POST /api/queue                 {stake}   (auth)       -> match view
  GET  /api/match/{match_id}         (auth)              -> match view
  POST /api/round/commit          {matchId, roundIndex, intentHash} (auth)
  POST /api/round/target          {matchId, roundIndex}  (auth) -> {targetMs, proof}
  POST /api/round/result          {matchId, roundIndex, measuredMs} (auth)
  POST /api/match/{match_id}/settle  (auth) -> engine settlement + oracle signature

Security model:
- Every privileged route requires a valid SIWE-derived session token.
- Match results are computed ONLY by match_engine.settle(); the oracle signs
  only engine output. Clients can never self-report a win into settlement.
- Match state persists to Firestore when credentials exist (P2.2a), so
  matchmaking and rounds survive instance recycling; falls back to in-memory
  for local dev.
"""

from __future__ import annotations

import hmac
import os
import re
import sys
import threading
import time
from typing import Any

import timebase
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import auth as _auth_module
import economy

# Single source of truth for the chain this deployment runs on. The SIWE
# statement, the oracle digest and the client (VITE_CHAIN_ID → CHAIN.chainId)
# must all agree — the audit regression was main.py hardcoding 137 while
# auth.py verified against 80002, so signing the server's OWN message 401'd.
import onchain

try:  # optional dependency — absent until Firestore credentials exist
    from google.cloud import firestore as _gcf  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - local dev without the SDK
    _gcf = None  # type: ignore[assignment]

import abuse
import analytics
import eligibility
import limits
import metrics

import oracle
from auth import EXPECTED_CHAIN_ID as _CHAIN_ID
from auth import NONCE_WINDOW_SECONDS as _NONCE_WINDOW
from auth import issue_nonce, issue_session, verify_session, verify_siwe
from match_engine import MATCH_TIMEOUT_SECONDS, MatchError, match_completed
from oracle import sign_settlement
from store import create_store, install_persistence

# --- Distributed rate limiting (audit #5, item 8) ----------------------------
# The audit asked for distributed limiting; there was NO limiter at all. This
# one is Firestore-backed (any replica sees the same window) with a per-process
# fallback for memory mode. Applied only to expensive/abusable endpoints.
_rl_lock = threading.Lock()
_rl_window: dict[str, list[float]] = {}
# Audit M16: the in-process fallback window is keyed by bucket+address and was
# never pruned, so it grew by one entry per IP/address ever seen. Past this cap
# the quiet windows are dropped (see `_rl_check`).
_RL_WINDOW_MAX_KEYS = 10_000
RL_WINDOW_SECONDS = 60.0
RL_QUEUE_MAX = 40        # queue calls per minute per address (audit #6 C3:
                         # the client's 2.5s poll = 24/min; 20/min kicked
                         # honest waiting players out of matchmaking at t≈50s)
RL_COMMIT_MAX = 40       # round commits per minute per address
RL_AUTH_MAX = 10         # SIWE handshakes per minute per address
RL_VERIFY_MAX = 30       # SIWE verifications per minute per IP (ecrecover is
RL_SETTLE_MAX = 10       # settle calls per minute per address (audit #10 #7:
                         # Firestore txn + signature minting per call)
RL_CLAIM_MAX = 10        # claim calls per minute per address (audit #10 #7:
                         # an RPC receipt fetch per call — cheap-DoS surface)
                         # CPU work; unthrottled it was a cheap DoS surface)
RL_ROUND_MAX = 60        # target reveals + result submissions per minute per
RL_USERNAME_LOOKUP_MAX = 60  # GET /api/username/{name} per minute per IP
RL_PLAYER_STATS_MAX = 60     # GET /api/player/{addr}/stats per minute per address
# Audit 2026-10-13: how long a rate-limit document may live. The window is 60s;
# an hour of slack means a TTL policy can never delete a row that is still being
# counted, while keeping the collection bounded.
RL_DOC_TTL_SECONDS = 3600
RL_CHALLENGES_MAX = 60       # GET /api/challenges per minute per address
                         # (audit #11 H3: without this the registry is
                         # enumerable — every possible name probed for free)
                         # address — hot endpoints that each trigger store work

# Audit #7 R3: limiter backend decoupling. The distributed (Firestore-backed)
# window previously activated only when onchain.escrow_configured() — two
# unrelated features coupled, so memory-mode deployments silently per-replica
# limited. Now: Firestore is the backend whenever the durable store is on.
# Firestore is ALWAYS the more correct backend; the in-process path remains
# only as the outage/memory-mode fallback.


def _rate_limited(retry_after: float) -> HTTPException:
    """Audit #7 R3: 429s must carry Retry-After so clients can back off by
    contract instead of hammering a full window."""
    return HTTPException(
        status_code=429,
        detail="Rate limit exceeded — slow down.",
        headers={"Retry-After": str(max(1, int(retry_after) + 1))},
    )


def _rl_check_ip(bucket: str, request: Request, limit: int) -> None:
    """Rate limit keyed by client IP instead of address (audit #6 C2/H7).

    Used where the caller's address is not yet known (/api/auth/verify) or
    where per-address limits are the wrong shape for cost control. Uses the
    same Firestore-backed (cross-replica) window when Firestore mode is on,
    otherwise the in-process fallback.

    Audit #10 (item 4): trusting X-Forwarded-For is now EXPLICIT, not inferred
    from "the socket looks like a private IP". Private-socket inference still
    trusts a proxy that rewrites XFF (Cloud Run / VPC L7 LB), but a deployment
    behind a proxy that PASSES the header through unmodified (nginx default,
    some edge workers) lets a client forge the first hop and shift its quota
    onto a victim IP. Set TRUST_PROXY_HEADERS=1 for such a topology AND make
    sure the proxy OVERWRITES X-Forwarded-For; leave it unset and the socket
    address is used directly (spoof-proof, just coarser per-NAT).
    """
    xff = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    socket_ip = request.client.host if request.client else "unknown"
    trust_xff = os.environ.get("TRUST_PROXY_HEADERS", "") in ("1", "true", "yes")
    socket_is_private = socket_ip.startswith(("10.", "172.", "192.168.", "127."))
    if hops and (trust_xff or (not trust_xff and socket_is_private)):
        # The proxy sits between us and the client; its REWRITTEN first hop is
        # the client. (A pass-through proxy makes this forgeable — that is why
        # the flag must only be set when the proxy overwrites the header.)
        ip = hops[0]
    else:
        ip = socket_ip or (hops[0] if hops else "unknown")
    _rl_check(bucket, f"{ip}|{socket_ip}" if hops and ip != socket_ip else ip, limit)


# Audit C1 — fallback observability. The limiter degrades to the in-process
# window when Firestore is unreachable (availability beats a hard 500 on a hot
# path), but a silent downgrade is how the original bug survived: the
# "distributed" limiter never worked and nothing said so. Every fallback is
# counted and surfaced on /api/health.
_rl_fallback_count = 0
_rl_fallback_last: dict[str, Any] = {}
# Phase 6.1: the DENOMINATOR. A fallback count with no total says nothing about
# how often the limiter is degraded relative to traffic.
_rl_attempts = 0


def _rl_note_fallback(exc: BaseException) -> None:
    global _rl_fallback_count
    _rl_fallback_count += 1
    _rl_fallback_last.clear()
    _rl_fallback_last.update({"error": repr(exc)[:200], "at": int(timebase.now())})
    print(
        f"[ratelimit] Firestore limiter unavailable — using the in-process window: {exc!r}",
        file=sys.stderr,
    )


def _rl_expiry(now_ms: int) -> Any:
    """The TTL stamp for a rate-limit document (audit 2026-10-13).

    Returns a `datetime` (what Firestore's TTL policy requires) when the SDK is
    available, and a plain epoch second otherwise so the field is still written
    and testable without the SDK.
    """
    expires_at = (now_ms // 1000) + RL_DOC_TTL_SECONDS
    try:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(expires_at, tz=UTC)
    except Exception:  # pragma: no cover - datetime is stdlib
        return expires_at


def _rl_check(bucket: str, address: str, limit: int) -> None:
    """Count one hit for (bucket, address) and refuse when over `limit`.

    Phase 6.1: every call increments `_rl_attempts`, so the fallback rate on
    /api/metrics has a denominator.

    Firestore mode uses a transactional read-modify-write on a rate_limits
    document so EVERY replica enforces the SAME window; memory mode is
    per-process. A Firestore outage degrades to in-process limiting instead of
    taking the endpoint down (fail-open for availability, never for money —
    the deposit gate below is fail-closed)."""
    global _rl_attempts
    _rl_attempts += 1
    fs = getattr(store, "_fs_store", None)
    if fs is not None:  # audit #7 R3: decoupled from onchain.escrow_configured()
        try:
            doc = fs.db.collection("rate_limits").document(f"rl:{bucket}:{address.lower()}")
            now_ms = int(timebase.now_ms())
            window_ms = int(RL_WINDOW_SECONDS * 1000)

            def _incr(txn: Any) -> dict[str, int]:
                snap = doc.get(transaction=txn)
                d = snap.to_dict() or {"count": 0, "reset_at": 0}
                if now_ms >= int(d.get("reset_at", 0)):
                    d = {"count": 1, "reset_at": now_ms + window_ms}
                else:
                    d = {"count": int(d.get("count", 0)) + 1, "reset_at": int(d["reset_at"])}
                # Audit 2026-10-13: nothing ever deleted these documents, so the
                # collection grew by one row per (bucket, address) FOREVER — an
                # unbounded storage cost on the hottest path. `expiresAt` is the
                # field a Firestore TTL policy deletes on; the policy itself is a
                # console/deploy step (see docs/DEPLOYMENT.md §3c).
                d["expiresAt"] = _rl_expiry(now_ms)
                txn.set(doc, d)
                return {"count": int(d["count"]), "reset_at": int(d["reset_at"])}

            # Audit C1: this used to call `_incr(txn)` as a plain function. A
            # `Transaction` from `db.transaction()` is NOT begun — only the
            # `@transactional` decorator calls `_begin()` — so the first
            # `doc.get(transaction=txn)` raised ValueError(INACTIVE_TXN), the
            # broad `except Exception: pass` swallowed it, and every deployment
            # silently fell back to per-process limiting. The decorator begins,
            # runs, and COMMITS the transaction (nothing else calls commit()).
            #
            # NB: the decorator comes from the firestore MODULE. `store._firestore`
            # is a DurableMatchStore *instance* attribute holding a Client, which
            # has no `transactional` — reading it here raised AttributeError.
            if _gcf is None:
                raise RuntimeError("google-cloud-firestore is required for the distributed limiter")
            win = _gcf.transactional(_incr)(fs.db.transaction())

            if win["count"] > limit:
                raise _rate_limited((win["reset_at"] - now_ms) / 1000.0)
            return
        except HTTPException:
            raise
        except Exception as exc:
            # Narrow by intent, not by type-blindness: a transient backend
            # problem degrades to the in-process window, but a programming
            # error (the INACTIVE_TXN class above) must surface as a 500 rather
            # than quietly disabling the distributed limiter again.
            if not _is_transient_backend_error(exc):
                raise
            _rl_note_fallback(exc)
            # fall through to the in-process window
    with _rl_lock:
        key = f"{bucket}:{address.lower()}"
        now = timebase.now()
        hits = [t for t in _rl_window.get(key, []) if now - t < RL_WINDOW_SECONDS]
        hits.append(now)
        _rl_window[key] = hits
        # Audit M16: a key was never removed, so the map grew by one entry per
        # IP/address ever seen. Past the cap, drop the quiet windows first (a
        # key whose newest hit is older than the window is indistinguishable
        # from absent), then the oldest ones — a hard bound, because an
        # unbounded fallback map is a leak an attacker can drive.
        if len(_rl_window) > _RL_WINDOW_MAX_KEYS:
            for stale in [k for k, v in _rl_window.items() if not v or now - v[-1] >= RL_WINDOW_SECONDS]:
                _rl_window.pop(stale, None)
            overflow = len(_rl_window) - _RL_WINDOW_MAX_KEYS
            if overflow > 0:
                for oldest, _ in sorted(_rl_window.items(), key=lambda kv: kv[1][-1])[:overflow]:
                    _rl_window.pop(oldest, None)
        if len(hits) > limit:
            raise _rate_limited(RL_WINDOW_SECONDS - (now - hits[0]))


def _is_transient_backend_error(exc: BaseException) -> bool:
    """True for backend/transport failures the in-process window can cover.

    Everything else (ValueError, TypeError, AttributeError, ...) is a bug in
    this module and must not be converted into a silent downgrade — that is
    precisely how audit C1 stayed invisible for the life of the project.
    """
    if isinstance(exc, OSError | TimeoutError | ConnectionError):
        return True
    try:
        from google.api_core import exceptions as gexc  # noqa: PLC0415

        return isinstance(exc, gexc.GoogleAPIError)
    except Exception:  # pragma: no cover — google-api-core missing
        return False


# --- Lazy sweep throttle (audit H9) ------------------------------------------
# `/api/queue` is the hottest endpoint (the client polls every 2.5s) and every
# poll ran the expiry sweep plus the stale-settlement re-sign, which between
# them issue three whole-collection scans. The sweep is a maintenance task, not
# part of answering the request, so it runs at most once per window.
SWEEP_MIN_INTERVAL_SECONDS = 15.0
_last_sweep_at = 0.0
_sweep_failures: dict[str, int] = {"sweep_expired": 0, "resign": 0, "total": 0}
_sweep_last_error: dict[str, Any] = {}


def _reset_sweep_clock() -> None:
    """Test seam: force the next poll to sweep."""
    global _last_sweep_at
    _last_sweep_at = 0.0


def _sweep_due() -> bool:
    """True when the maintenance sweep may run again (audit H9)."""
    global _last_sweep_at
    now = timebase.now()
    if now - _last_sweep_at < SWEEP_MIN_INTERVAL_SECONDS:
        return False
    _last_sweep_at = now
    return True


def _note_sweep_failure(where: str, exc: BaseException) -> None:
    """A silent sweep failure looks exactly like a working one (audit H9).

    The durable re-sign sweep (the F-12 prize rescue) can be dead in production
    because a missing composite index raises and the old `except: pass` hid it.
    Count it and surface it on /api/health.
    """
    _sweep_failures[where] = _sweep_failures.get(where, 0) + 1
    _sweep_failures["total"] += 1
    _sweep_last_error.clear()
    _sweep_last_error.update(
        {"where": where, "error": repr(exc)[:200], "at": int(timebase.now())}
    )
    print(f"[sweep] {where} failed: {exc!r}", file=sys.stderr)


def sweep_health() -> dict[str, Any]:
    return {
        "minIntervalSeconds": SWEEP_MIN_INTERVAL_SECONDS,
        "lastRunAt": int(_last_sweep_at),
        "failures": dict(_sweep_failures),
        "lastError": dict(_sweep_last_error),
    }


# Audit H19: the contract's permissionless refund opens at
# MATCH_TIMEOUT + REFUND_GRACE, not at MATCH_TIMEOUT. User-facing copy must
# state the real window or a player follows the instruction and gets a revert.
REFUND_GRACE_SECONDS = 10 * 60  # == PulsarEscrow.REFUND_GRACE
REFUND_HORIZON_SECONDS = MATCH_TIMEOUT_SECONDS + REFUND_GRACE_SECONDS


# Joiner-deposit timeout (audit #5, item 3): if the joiner's stake never lands
# on-chain within this window after matchmaking, the match is voided so the
# creator can refund (refundTimeoutMatch) instead of being locked for the
# on-chain refund horizon (MATCH_TIMEOUT + REFUND_GRACE).
DEPOSIT_TIMEOUT_SECONDS = 300.0


def _is_store_contention(exc: BaseException) -> bool:
    """True when the store failed because it was BUSY, not because we were wrong.

    Firestore's transaction helper gives up after a fixed number of retries and
    raises a plain `ValueError`; the message is the only signal it offers. A
    busy store is transient and retryable, so it must not be reported as a 500.
    """
    text = str(exc).lower()
    return "failed to commit transaction" in text or "aborted" in text or "contention" in text


def _gate_or_void(match_id: str) -> None:
    """Run the on-chain deposit gate BEFORE the store lock is taken (audit H10).

    The gate is a blocking network read (up to RPC_TIMEOUT_SECONDS = 5) and the
    in-memory store holds ONE global lock for every match, so calling it from
    inside `store.update`'s mutate serialized every commit / reveal / submit /
    settle in the process — a single slow RPC stalled all matchmaking. On
    Firestore it also held an open transaction across socket I/O.

    Safe to run on a snapshot: the gate's inputs (`stake`, `players`) are
    immutable after activation, and the on-chain state is external anyway.

    Raises 409 when the round must be refused, and persists the void when the
    on-chain duel is provably a different match.
    """
    if not onchain.escrow_configured():
        return  # practice / unconfigured dev — gate inactive
    # `identity` is the mirror-backed read: the gate's inputs are immutable, and
    # the on-chain state below is still read fresh. Saves one Firestore read per
    # round action (audit 2026-10-14, plan item 10.3).
    snapshot = store.identity(match_id)
    gate = _verify_deposits_or_void(snapshot)
    if not gate:
        return
    if gate.get("void"):
        _persist_void(match_id)
    raise HTTPException(status_code=409, detail=gate["reason"])


def _persist_void(match_id: str) -> None:
    """Persist a gate void decision in its own short transaction (audit H10)."""

    def _void(m: Any, eng: Any) -> None:
        # Audit 2026-10-13: this set `void` unconditionally. If a concurrent
        # replica settled the match between the gate's snapshot and this write,
        # the status flipped settled -> void while the signed envelope survived —
        # the ledger then skipped a settlement the chain had already paid.
        if m.status in ("settled", "void"):
            return None
        m.status = "void"
        return None

    try:
        store.update(match_id, _void)
    except (MatchError, HTTPException):
        pass  # the 409 below is the caller-visible outcome either way


def _verify_deposits_or_void(m: Any) -> dict[str, Any] | None:
    """On-chain deposit gate for round actions. Returns None to proceed.

    Fail-CLOSED: when escrow mode is configured but the deposit state cannot
    be read, rounds are refused — a custom client that never stakes must not
    be able to grief an honest opponent's locked deposit.

    Audit #8 F-03: the gate now validates the WHOLE duel, not just its status:
      - status must be Active (both stakes locked),
      - the on-chain stakeAmount must equal the server's agreed stake
        (converted with the token's real decimals — a creator cannot lock
        the match with a dust stake while the UI promises the full prize),
      - the on-chain player1/player2 must be exactly the server's two
        participants (depositing from a different wallet then playing as
        another one makes the winner unpayable — the contract rejects a
        winner that is not player1/player2, so the honest player would burn
        the full refund horizon of locked stake on an unwinnable match).
    Also voids the server-side match when the joiner's deposit never arrives
    (audit #8 F-05: the deposit timeout counts from ACTIVATION, not queue
    entry)."""
    if not onchain.escrow_configured():
        return None  # practice / unconfigured dev — gate inactive
    info = onchain.duel_info(m.match_id)
    if info is None:
        raise HTTPException(
            status_code=409,
            detail="On-chain deposit state is temporarily unreadable — retry shortly.",
        )
    if info.get("status") == onchain.STATUS_ACTIVE:
        # F-03: stake amount + participants must match the server's match
        # (single source of truth: onchain.deposit_verdict — probe-testable).
        #
        # Audit C2: UNKNOWN (the chain could not be read) is NOT a mismatch. It
        # must refuse the round, never void the match — voiding on a transient
        # RPC failure destroys a live duel and costs the winner their prize.
        verdict = onchain.deposit_verdict(info, m.stake, m.players)
        if verdict is onchain.DepositVerdict.UNKNOWN:
            raise HTTPException(
                status_code=409,
                detail=(
                    "On-chain duel state cannot be verified right now — retry shortly. "
                    "The match is untouched."
                ),
            )
        if verdict is onchain.DepositVerdict.MISMATCH:
            # Audit H10: do NOT mutate here — this runs outside the store
            # transaction now, so the caller persists the void explicitly.
            return {
                "void": True,
                "reason": (
                    "On-chain duel does not match this match (stake or "
                    "participants differ) — the match is void. Both stakes "
                    "refund via refundTimeoutMatch after the escrow timeout "
                    "(MATCH_TIMEOUT + REFUND_GRACE)."
                ),
            }
        return None  # both stakes locked AND the duel is genuinely this match — play on
    if info.get("status") == onchain.STATUS_CREATED:
        # Audit #8 F-05: the deposit timeout counts from ACTIVATION (when the
        # joiner paired), not from queue entry — a long-queued match must not
        # be voided the moment it finally pairs.
        clock_origin = m.play_started_at()
        if timebase.now() - clock_origin > DEPOSIT_TIMEOUT_SECONDS:
            # Audit H10: the caller persists the void (see _gate_or_void).
            # H4 — honest money-UX: the contract only releases refunds at
            # createdAt + MATCH_TIMEOUT (30 min). Saying "refundable now" sends
            # players into a revert for ~25 minutes. State the real window.
            return {
                "void": True,
                "reason": (
                    "Opponent stake deposit timed out — the match is void. The "
                    "creator's stake becomes refundable on-chain via "
                    "refundTimeoutMatch after the escrow timeout (MATCH_TIMEOUT + REFUND_GRACE)."
                ),
            }
    raise HTTPException(
        status_code=409,
        detail="On-chain deposits are not verified for this match yet.",
    )


def _nonce_of(message: str) -> str:
    fields = _auth_module.parse_siwe(message)
    return fields.nonce if fields else ""


def _siwe_message(address: str, nonce: str, domain: str) -> str:
    """Canonical SIWE statement. Chain ID comes from the deployment constant
    and Issued At is DERIVED from the nonce's time window — both fully
    deterministic per (address, nonce, domain), so the exact issued message
    can be recomputed at verify time on any replica (no server-side session
    store needed)."""
    import datetime as _dt

    window = _auth_module.nonce_window(nonce) or 0
    issued_at = _dt.datetime.fromtimestamp(
        window * _NONCE_WINDOW, tz=_dt.UTC
    ).isoformat()
    return (
        f"{domain} wants you to sign in with your Polygon account:\n"
        f"{address.lower()}\n"
        "\n"
        "Prove you own this wallet. This signature grants no permission to move funds or spend tokens.\n"
        "\n"
        f"URI: https://{domain}\n"
        "Version: 1\n"
        f"Chain ID: {_CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
    )

app = FastAPI(title="PULSAR Game Server", version="1.1.1")


@app.exception_handler(Exception)
async def _store_contention_handler(request: Request, exc: Exception) -> JSONResponse:
    """A BUSY store is a retryable 503, on EVERY route.

    Audit 2026-10-14 (found by the 1000-poller load run): Firestore's
    transaction helper gives up after a fixed number of retries and raises
    `ValueError: Failed to commit transaction in 5 attempts`. That escaped as an
    HTTP 500 — which tells a client "this is broken, do not retry" — on 157 of
    157 queue requests, and on `/api/challenges` and `/api/player/{addr}/stats`
    too. The request was fine; the store was busy.

    Handled once here rather than per route, because the first fix covered only
    `/api/queue` and the same failure kept surfacing on the other endpoints.
    """
    if _is_store_contention(exc):
        metrics.note_store_contention()
        return JSONResponse(
            status_code=503,
            content={"detail": "Matchmaking is busy — retry shortly."},
            headers={"Retry-After": "1"},
        )
    # Anything else is a real error: let FastAPI's default handling report it.
    raise exc

# Audit H6 — production configuration is MANDATORY, and the default is INVERTED.
#
# History, because the comments here used to describe three different policies:
#   - audit #8 F-09: fail startup when the deployment "looks like production";
#   - audit #10 item 2: that check was `PULSAR_ENV == "production"` EXACTLY, so
#     one typo ("prod", "Production ") switched every safeguard off;
#   - audit H6: even the widened version only fired for a fixed set of
#     PULSAR_ENV strings or one of five platform markers, so a self-hosted
#     Docker/VM deployment with neither ran with no required-env enforcement,
#     wildcard CORS, no TrustedHost middleware and a Host-derived SIWE domain.
#
# The policy now: EVERY environment is production-like unless it explicitly
# opts out with PULSAR_ENV=dev. Forgetting to set a variable must not disable
# the safeguards. See `_is_prod_like` / `_missing_production_env`.
#
# Now: EVERY environment is production-like unless it explicitly opts out with
# PULSAR_ENV=dev. Forgetting to set a variable must not disable the safeguards.
_LOCAL_ENV_VALUES = {"dev", "development", "test", "local"}
_DEPLOY_MARKERS = ("K_SERVICE", "K_REVISION", "RENDER", "FLY_MACHINE_ID", "DYNO")
REQUIRED_PRODUCTION_ENV = (
    "ALLOWED_DOMAIN",
    "CORS_ALLOW_ORIGINS",
    "ESCROW_ADDRESS",
    "ESCROW_RPC_URL",
    "ORACLE_SIGNING_SECRET",
    "ORACLE_PRIVATE_KEY",
    # Audit 2026-10-13: this was missing, and both `auth` and `oracle` default it
    # to 80002 (Amoy). A production deployment that forgot it would sign SIWE
    # statements and settlement digests for a TESTNET while the escrow is on
    # Polygon — the failure is a rejected signature, and the only signal was an
    # env var the gate did not require.
    "ORACLE_CHAIN_ID",
)


def _is_prod_like(environ: Any) -> bool:
    """True when this process must not run with insecure defaults (audit H6)."""
    if str(environ.get("PULSAR_ENV", "")).strip().lower() in _LOCAL_ENV_VALUES:
        return False
    return True


def _missing_production_env(environ: Any) -> list[str]:
    """The required variables this deployment has not set (audit H6)."""
    return [name for name in REQUIRED_PRODUCTION_ENV if not environ.get(name)]


_prod_like = _is_prod_like(os.environ)
if _prod_like:
    _missing = _missing_production_env(os.environ)
    if _missing:
        raise RuntimeError(
            "Production-like deployment requires these env vars to be set: "
            + ", ".join(_missing)
            + ". Refusing to start with an insecure default. "
            "Set PULSAR_ENV=dev to explicitly opt out for local testing."
        )

# Audit #10 (item 2): an INCOHERENT escrow config (one half set, the other
# missing) silently disables the deposit gate (onchain.escrow_configured()
# requires BOTH) while the deployment believes it has one. In dev/test the
# address is deliberately configured without an RPC to keep the gate off, so
# this is a loud warning, not a crash — the prod-like gate above still
# requires the full set when money mode is real.
if bool(os.environ.get("ESCROW_ADDRESS")) != bool(os.environ.get("ESCROW_RPC_URL")):
    print(
        "[config] WARNING: ESCROW_ADDRESS and ESCROW_RPC_URL are not both set — "
        "the on-chain deposit gate is INACTIVE. This is safe only for local "
        "dev/test, never for a real-money deployment.",
        file=sys.stderr,
    )

# Audit #8 F-09 — TrustedHost: requests with a foreign Host header are rejected
# at the middleware layer instead of being trusted for SIWE domain binding
# (host-header injection hardening).
#
# Audit 2026-10-13 (found by the phase-10 E2E setup): this used ALLOWED_DOMAIN —
# which is the FRONTEND's public host, the value the SIWE statement is bound to.
# In the documented split topology (frontend on app.example.com, API on
# api.example.com) the browser sends `Host: api.example.com`, the allowlist held
# only `app.example.com`, and **every request to the API was rejected with 403**.
# The API was unreachable in exactly the deployment the runbook describes.
#
# The two are different values, so they are different variables now:
#   ALLOWED_HOSTS  — the hostnames THIS API answers to (defaults to
#                    ALLOWED_DOMAIN, which is correct only when they share one).
#   ALLOWED_DOMAIN — the SIWE domain, unchanged.
_allowed_domain = os.environ.get("ALLOWED_DOMAIN", "")
_allowed_hosts = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", _allowed_domain).split(",")
    if h.strip()
]
if _allowed_hosts:
    try:
        from fastapi.middleware.trustedhost import TrustedHostMiddleware

        expanded = list(_allowed_hosts)
        for host in _allowed_hosts:
            expanded.append(host.removeprefix("www."))
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=expanded)
    except Exception:  # pragma: no cover — older FastAPI without the middleware
        pass

# P0-fix — CORS. The frontend (static hosting) and this API are commonly on
# different origins (docs/DEPLOYMENT.md deployment topology), so browsers send
# preflights for the JSON + Authorization requests the client makes. Without
# this middleware every cross-origin call died in the browser. Origins are
# env-configured; "*" (default) allows credentialess public play from any
# origin — this API is bearer-token authenticated, never cookie-authenticated,
# so wildcard origins are safe.
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
]
# Audit #10 (item 2): "*" stays available for credentialess local dev, but a
# production-like deployment that somehow kept it (e.g. CORS_ALLOW_ORIGINS=*,
# bypassing the required-env gate above) is downgraded to the SIWE domain —
# bearer tokens from arbitrary origins are exactly the replay surface the
# audits keep flagging.
if _prod_like and _cors_origins == ["*"]:
    _fallback_origin = f"https://{_allowed_domain}" if _allowed_domain else ""
    if _fallback_origin:
        _cors_origins = [_fallback_origin]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=86400,
)

# Stakes the lobby offers (src/pages/LobbyPage.tsx STAKE_TIERS). Anything else
# is rejected, so the queue can never be polluted with arbitrary values.
ALLOWED_STAKES = frozenset({1.0, 2.0, 5.0, 10.0})

# P2.4 — server error monitoring. No-ops unless SENTRY_DSN is set in the
# server environment. Never required for local dev.
_server_dsn = os.environ.get("SENTRY_DSN", "")
if _server_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=_server_dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            traces_sample_rate=0.0,
            send_default_pii=False,
            integrations=[FastApiIntegration()],
        )
    except Exception:
        pass  # monitoring must never prevent startup

store = create_store()

# P2.2a — persistence wiring. The engine mutators are wrapped with a save
# hook, and this module calls them THROUGH the module object so the wrapped
# versions (not stale by-name imports) are always used.
import match_engine as engine  # noqa: E402  (after env-backed imports)

install_persistence(store, engine)
commit_intent = engine.commit_intent
reveal_target = engine.reveal_target
submit_result = engine.submit_result
settle = engine.settle
ROUNDS = engine.ROUNDS



@app.middleware("http")
async def _record_metrics(request: Request, call_next: Any) -> Any:
    """Time every request for /api/metrics (phase 6.1).

    Uses the ROUTE TEMPLATE FastAPI resolved, not the raw path, so per-match ids
    do not each become their own entry. `/api/metrics` itself is skipped:
    otherwise every scrape perturbs the numbers it reports.
    """
    started = time.perf_counter()
    reads_before = metrics.firestore_reads_total()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    if path != "/api/metrics":
        metrics.observe_request(request.method, path, (time.perf_counter() - started) * 1000.0)
        # Attribute this request's Firestore reads to its route, so
        # `readsPerMatch` can be acted on rather than merely reported.
        metrics.note_firestore_reads_for_route(
            path, metrics.firestore_reads_total() - reads_before
        )
    return response


# --- admin tooling (phase 6.3 / G9) -------------------------------------------
#
# Gated by a SEPARATE secret, not a session token: a session token belongs to a
# player, and a player must never be able to void their opponent's match.
# If the secret is UNSET the routes are DISABLED, not open — an unconfigured
# deployment must fail closed.
_ADMIN_SECRET = os.environ.get("PULSAR_ADMIN_SECRET", "").strip()


class AdminActionRequest(BaseModel):
    # An unaudited money-moving action is worse than no action: the record must
    # say WHY, not just who.
    reason: str = Field(min_length=3, max_length=500)


def _admin_get_match(match_id: str) -> Any:
    """Fetch a match for an admin route, or None.

    `store.get` RAISES `MatchError("Match not found")` rather than returning
    None, so a missing match would surface as a 500 instead of a 404.
    """
    try:
        return store.get(match_id)
    except MatchError:
        return None


def _require_admin(request: Request) -> None:
    """Refuse unless the admin secret matches. Fails CLOSED when unset."""
    if not _ADMIN_SECRET:
        raise HTTPException(status_code=404, detail="Not found")
    supplied = request.headers.get("X-Admin-Secret", "")
    if not supplied or not hmac.compare_digest(supplied, _ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Admin credential required")


@app.get("/api/admin/match/{match_id}")
def admin_inspect_match(match_id: str, request: Request) -> dict[str, Any]:
    """Full match state for an operator (phase 6.3)."""
    _require_admin(request)
    if not re.fullmatch(r"[0-9a-f]{32}", match_id):
        raise HTTPException(status_code=422, detail="Invalid match id")
    m = _admin_get_match(match_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return {
        "matchId": m.match_id,
        "status": m.status,
        "stake": m.stake,
        "players": list(m.players),
        "creator": m.creator,
        "joiner": m.joiner,
        "winner": m.winner,
        "createdAt": m.created_at,
        "activatedAt": m.activated_at,
        "settledAt": m.settled_at,
        "minRttMs": dict(m.min_rtt_ms),
        "hasSignature": m.signed_settlement is not None,
        "rounds": {
            addr: {
                str(idx): {
                    "committed": bool(r.commit_hash),
                    "revealed": r.revealed,
                    "submitted": r.result_ms is not None,
                    "valid": r.valid,
                    "rejectReason": r.reject_reason,
                }
                for idx, r in sorted(rounds.items())
            }
            for addr, rounds in m.rounds.items()
        },
    }


@app.get("/api/admin/players")
def admin_player_search(request: Request, q: str = "") -> dict[str, Any]:
    """Find a player's matches by address (phase 6.3).

    The query must be a full address: free text would be an unbounded Firestore
    scan, which is both slow and a cost amplifier.
    """
    _require_admin(request)
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", q or ""):
        raise HTTPException(status_code=422, detail="Query must be a full 0x address")
    addr = q.lower()
    # The durable store exposes the idempotency map through its memory
    # backend; there is no top-level attribute (found by the admin tests).
    live = getattr(store, "player_match", None) or store.memory.player_match.get(addr)
    matches = []
    if live:
        m = _admin_get_match(live)
        if m is not None:
            matches.append({"matchId": m.match_id, "status": m.status, "stake": m.stake})
    return {"address": addr, "matches": matches}


@app.post("/api/admin/match/{match_id}/void")
def admin_force_void(match_id: str, body: AdminActionRequest, request: Request) -> dict[str, Any]:
    """Void a match that cannot complete, refunding both (phase 6.3)."""
    _require_admin(request)
    if not re.fullmatch(r"[0-9a-f]{32}", match_id):
        raise HTTPException(status_code=422, detail="Invalid match id")
    m = _admin_get_match(match_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if m.status in ("settled", "void"):
        raise HTTPException(status_code=409, detail=f"Match is already {m.status}")

    # Audit 2026-10-13: this mutated the object and called `store.put` — a blind
    # `set` OUTSIDE the store transaction, so a concurrent participant settle
    # could be clobbered (a settled match overwritten to void while its signed
    # envelope survived). Route it through `store.update`, which is the one
    # serialized read-modify-write, and re-check the status INSIDE it.
    def _void(match: Any, _eng: Any) -> str:
        if match.status in ("settled", "void"):
            return match.status
        match.status = "void"
        return "void"

    outcome = store.update(match_id, _void)
    if outcome != "void":
        raise HTTPException(status_code=409, detail=f"Match is already {outcome}")
    print(
        f"[admin] force-void {match_id} reason={body.reason!r}",
        file=sys.stderr,
    )
    return {"matchId": match_id, "status": "void", "reason": body.reason}


@app.post("/api/admin/match/{match_id}/settle")
def admin_force_settle(match_id: str, body: AdminActionRequest, request: Request) -> dict[str, Any]:
    """Settle a match the engine considers complete (phase 6.3)."""
    _require_admin(request)
    if not re.fullmatch(r"[0-9a-f]{32}", match_id):
        raise HTTPException(status_code=422, detail="Invalid match id")
    m = _admin_get_match(match_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Match not found")

    # Audit 2026-10-13: this settled the object and called `store.put` — a blind
    # `set` outside the store transaction, racing a concurrent participant
    # settle. `_settle_once` is the ONE transactional settlement body (settle →
    # sign → attach, plus the rating update); the admin path now uses it, so the
    # two cannot diverge and the write is serialized.
    try:
        signed = store.update(match_id, _settle_once)
    except MatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _ledger_settlement(match_id)
    print(
        f"[admin] force-settle {match_id} reason={body.reason!r}",
        file=sys.stderr,
    )
    return {"matchId": match_id, "reason": body.reason, "settlement": signed}


class DisputeRequest(BaseModel):
    matchId: str = Field(pattern=r"^[0-9a-f]{32}$")
    # Bounded: an unbounded field is a way to fill the database.
    reason: str = Field(min_length=3, max_length=1000)


@app.post("/api/dispute")
def report_dispute(body: DisputeRequest, request: Request) -> dict[str, Any]:
    """Report a match for review (phase 6.4 / G8).

    A report is a REQUEST FOR REVIEW, not an action: this handler never touches
    match state or the money path. The reporter cannot change the outcome, and
    the test asserts that by inspecting this function's source.

    Only a participant may report. Anyone else reporting a match they were not in
    is noise at best and harassment at worst.
    """
    address = _auth(request)
    m = _admin_get_match(body.matchId)
    if m is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if address.lower() not in m.players:
        # 404 rather than 403: a non-participant should not learn that the match
        # exists.
        raise HTTPException(status_code=404, detail="Match not found")

    report = {
        "matchId": body.matchId,
        "reporter": address.lower(),
        "reason": body.reason,
        "at": int(timebase.now()),
        "status": m.status,
    }
    # Stored under the match so an operator inspecting it finds the report
    # alongside the state it is about.
    store.record_dispute(body.matchId, report)
    print(
        f"[dispute] {body.matchId} from {address.lower()}: {body.reason[:120]!r}",
        file=sys.stderr,
    )
    return {"ok": True, "matchId": body.matchId, "received": report["at"]}


@app.get("/api/metrics")
def metrics_endpoint() -> dict[str, Any]:
    """Operational metrics (phase 6.1).

    Answers "how well", where /api/health answers "is it up". Per-process: with
    N replicas each reports its own, and aggregating them is the monitoring
    system's job rather than the server's.
    """
    body = metrics.snapshot()
    # Fold in the counters that already live in main, so there is ONE place to
    # scrape rather than two.
    body["rateLimit"] = {
        "fallbacks": _rl_fallback_count,
        "fallbackRate": (
            round(_rl_fallback_count / _rl_attempts, 4) if _rl_attempts else None
        ),
        "attempts": _rl_attempts,
        "lastFallback": dict(_rl_fallback_last),
    }
    return body


def _oracle_address_or_none() -> str | None:
    """The oracle's address, or None when the signer is not configured.

    The health endpoint must answer even when the server is misconfigured —
    that is the whole point of a probe.
    """
    try:
        return oracle.oracle_address()
    except Exception:  # noqa: BLE001 — a probe reports, it does not raise
        return None


@app.get("/api/ping")
def ping() -> dict[str, Any]:
    """Zero-I/O round-trip probe (audit H-03, 2026-10-22).

    The client measures its RTT here and sends it with `POST /api/queue`, where
    the ping cap decides whether the connection is fair enough to stake on.

    This exists because `/api/health` was doing double duty: it reports RPC
    reachability, chain id and token decimals, all of which can perform chain
    I/O. Measuring "network latency" against an endpoint that may wait on a
    remote node conflates the player's connection with the operator's RPC — a
    player on fibre could be refused for the server's problem, and the number
    was unstable by design.

    Nothing here touches the store, the chain, or the clock beyond one integer.
    Deliberately unauthenticated: it reveals nothing, and requiring a session
    would add an auth round trip to the measurement.
    """
    return {"ok": True, "t": timebase.now_ms()}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "pulsar-game-server",
        "rounds": ROUNDS,
        "matchStore": store.backend_name,  # honest visibility for ops
        # Audit #10 (item 6): surface ledger health so a silently-dead economy
        # ledger shows up in monitoring, not in payout disputes.
        "ledger": economy.ledger_health(),
        # P0-fix: ops visibility without leaking secrets — mismatch between
        # ORACLE_CHAIN_ID / VITE_CHAIN_ID bricks every settlement sig.
        "chainId": _CHAIN_ID,
        "escrowConfigured": onchain.escrow_configured(),
        "prodLike": _prod_like,
        # Audit C1: the distributed limiter silently degraded to a per-process
        # window for the life of the project. Expose which backend is actually
        # enforcing and how often it fell back, so a dead distributed limiter is
        # visible in monitoring instead of being discovered during an incident.
        # Audit H9: a dead sweep (e.g. a missing composite index) must be
        # visible in monitoring, not discovered when a prize goes unclaimed.
        "sweep": sweep_health(),
        # Audit 6.2: the three questions an operator asks during an incident and
        # could not previously answer from the server. No secret and no URL:
        # this endpoint is unauthenticated, so anything here is public.
        "rpc": {
            "configured": bool(os.environ.get("ESCROW_RPC_URL")),
            "reachable": onchain.chain_reachable(),
            "chainId": onchain.rpc_chain_id(),
        },
        "tokenDecimals": onchain.token_decimals(),
        # Public by design: it is in every settlement packet. An operator needs
        # it to confirm the deployed contract trusts the key we hold.
        #
        # Audit 2026-10-13 (found by the phase-10 load run): this called
        # `oracle_address()` unguarded, and `load_signer()` RAISES when
        # ORACLE_PRIVATE_KEY is absent — so /api/health answered 500. A liveness
        # probe that fails instead of reporting turns "the oracle key is
        # missing" into a crash loop, and the operator sees a restarting
        # container rather than the one fact they need.
        "oracleAddress": _oracle_address_or_none(),
        "oracleConfigured": _oracle_address_or_none() is not None,
        "rateLimit": {
            "backend": "firestore" if getattr(store, "_fs_store", None) is not None else "memory",
            "fallbacks": _rl_fallback_count,
            "lastFallback": dict(_rl_fallback_last),
        },
    }


def _request_domain(request: Request) -> str:
    """The SIWE domain this server issues statements for (audit H7).

    The nonce MAC and the canonical message are both bound to this value, so
    taking it from the request's `Host` header let an attacker choose the domain
    the server issued and accepted statements for — the phishing resistance the
    design claims, removed by a header.

    Resolution order:
      1. ALLOWED_DOMAIN (the configured public host) — always wins;
      2. PUBLIC_HOST — the explicit fallback for a deployment that has not set
         ALLOWED_DOMAIN yet;
      3. the Host header, ONLY when the escrow is unconfigured (local dev, where
         there is no money and no real domain to protect).
    """
    override = os.environ.get("ALLOWED_DOMAIN", "").strip()
    if override:
        return override
    public_host = os.environ.get("PUBLIC_HOST", "").strip()
    if public_host:
        return public_host
    if onchain.escrow_configured():
        # Money mode with no configured domain: refuse to invent one from a
        # client-controlled header.
        raise HTTPException(
            status_code=503,
            detail=(
                "Server misconfigured: ALLOWED_DOMAIN (or PUBLIC_HOST) must be set "
                "when the escrow is configured."
            ),
        )
    return request.headers.get("host", "localhost")


def _is_address(value: str) -> bool:
    """A full lowercase-or-mixed-case EVM address (audit M27)."""
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", value or ""))


def _auth_staked(request: Request) -> str:
    """Authenticate AND require the eligibility attestation (plan item 11.3/G2).

    Used on `/api/queue` — the ENTRY to staked play — and deliberately NOT on the
    round, settle or claim endpoints.

    That is not an oversight. A gate on the downstream endpoints would TRAP FUNDS:
    a player who reached a duel and then failed an attestation check could not
    play, could not settle, and could not claim — their stake would sit in the
    escrow until the refund window. A compliance gate that can strand money is
    worse than the gap it closes. Gate the door, never the exit.

    Free play is not gated either: it involves no money, and a gate that blocks
    practice only teaches players to bypass gates.
    """
    address = _auth(request)
    try:
        eligibility.require(address)
    except eligibility.EligibilityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return address


def _auth(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    address = verify_session(header.removeprefix("Bearer ").strip())
    if not address:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return address


class NonceRequest(BaseModel):
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")


class VerifyRequest(BaseModel):
    message: str = Field(max_length=4096)
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]+$", max_length=512)


class QueueRequest(BaseModel):
    stake: float
    # Audit H1: the ping cap needs the round trip AT QUEUE TIME. It was only
    # sent with the round result, so the cap was unreachable from HTTP and the
    # gate existed only in the unit tests.
    #
    # Audit H-03 (2026-10-22): the field was OPTIONAL, so a client could omit it
    # and skip the cap entirely — and the cap is the only place a laggy player is
    # kept out of a fair match. A protocol field that can be left out is not a
    # gate. It is required now, and the client measures it against the zero-I/O
    # `/api/ping` (previously `/api/health`, which can perform RPC I/O and
    # inflated the measurement it was supposed to bound).
    rttMs: float = Field(ge=0, le=10_000)
    # Audit M27: a friend challenge names the address it is reserved for. The
    # match is not offered to anyone else, and it is satisfied when that
    # address queues (naming the challenger, or simply queueing).
    opponent: str | None = Field(default=None, max_length=42)


class CommitRequest(BaseModel):
    # P0-fix: matchId is server-generated token_hex(16) — pin the shape so
    # `a/b` can never become a Firestore subcollection reference.
    matchId: str = Field(pattern=r"^[0-9a-f]{32}$")
    roundIndex: int
    intentHash: str = Field(pattern=r"^0x[0-9a-f]{64}$")


class TargetRequest(BaseModel):
    matchId: str = Field(pattern=r"^[0-9a-f]{32}$")
    roundIndex: int


class ResultRequest(BaseModel):
    matchId: str = Field(pattern=r"^[0-9a-f]{32}$")
    roundIndex: int
    measuredMs: float = Field(gt=0, le=5000)
    # P0-fix (audit #2): unforgeable per-player proof issued at reveal. Without
    # it the stored result was disconnected from its commit (any 90ms claim
    # after any commit was accepted).
    resultProof: str = ""
    # Audit H1: the client's measured round trip, used to compensate the
    # server-observed reaction for network distance. Optional so an older client
    # still plays (uncompensated) rather than failing; bounded so an absurd
    # report cannot be used to farm compensation — the engine keeps the MINIMUM
    # across the match anyway.
    rttMs: float | None = Field(default=None, ge=0, le=10_000)


class ClaimRequest(BaseModel):
    txHash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    # Audit 8.14: this carried a `signature` field that nothing ever read — the
    # claim is authenticated by the SIWE session and verified against the chain
    # receipt, so a second signature proved nothing. A field the server ignores
    # is worse than no field: it invites a client to believe it matters.


@app.post("/api/auth/nonce")
def auth_nonce(body: NonceRequest, request: Request) -> dict[str, str]:
    # Audit #8 F-10: the nonce bucket was keyed ONLY by the client-supplied
    # address — rotating addresses bypassed the limit (soft-lock DoS on a
    # victim's login). Now it's the composite IP+address bucket: still fair to
    # a single honest client, blind to address rotation.
    _rl_check_ip("auth", request, RL_AUTH_MAX)
    domain = _request_domain(request)
    nonce = issue_nonce(body.address, domain)
    return {"nonce": nonce, "message": _siwe_message(body.address, nonce, domain)}


@app.post("/api/auth/verify")
def auth_verify(body: VerifyRequest, request: Request) -> dict[str, str]:
    # Audit #6 C2: /verify runs ecrecover (CPU work) and used to be the only
    # unthrottled crypto endpoint. Forged-nonce spam is now both REJECTED by
    # the MAC check and rate-limited here — one bucket for the whole endpoint
    # (the client signs a message it has not parsed yet, so the address is
    # unknown until after verification).
    _rl_check_ip("verify", request, RL_VERIFY_MAX)
    domain = _request_domain(request)
    recovered = verify_siwe(body.message, body.signature, domain)
    if not recovered:
        raise HTTPException(status_code=401, detail="SIWE verification failed")
    # Challenge-binding: the submitted statement must be the exact canonical
    # message this server issued (same chain, same statement lines) and carry
    # the nonce from OUR issuance. Prevents client-crafted or chain-scrambled
    # statements from authenticating even when the MAC nonce is valid.
    expected = _siwe_message(recovered, _nonce_of(body.message), domain)
    if body.message != expected:
        raise HTTPException(status_code=401, detail="SIWE message does not match the issued challenge")
    return {"token": issue_session(recovered), "address": recovered}


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict[str, bool]:
    """Revoke the caller's session (audit H22).

    `auth.revoke_session()` existed but was reachable from nowhere, so a leaked
    token stayed valid for its full 2h TTL. This is the endpoint that makes the
    F-06 mitigation real. Revocation is per-jti, so logging out one device does
    not sign the user out everywhere.
    """
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header.removeprefix("Bearer ").strip()
    if not verify_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    jti = _auth_module.session_jti(token)
    if not jti:
        # A token we cannot attribute to a jti cannot be revoked; saying "ok"
        # here would be a lie the client acts on.
        raise HTTPException(status_code=500, detail="Session has no revocation id")
    if not _auth_module.revoke_session(jti):
        raise HTTPException(
            status_code=503,
            detail="Logout could not be recorded — the session is still valid. Retry.",
        )
    return {"ok": True}


class BanRequest(BaseModel):
    address: str
    seconds: int
    # REQUIRED: an unexplained ban is not auditable (api/abuse.py).
    reason: str


@app.get("/api/abuse")
def abuse_state(request: Request) -> dict[str, Any]:
    """The caller's own abuse state (plan item 11.3 / G6)."""
    return abuse.state(_auth(request))


@app.get("/api/admin/analytics")
def admin_analytics(request: Request) -> dict[str, Any]:
    """Product analytics, computed from the server's own records.

    Admin-only: it is operator data, not player data. And it is computed rather
    than collected — no third party, no cookies, no client script, no PII. See
    api/analytics.py for why that is the whole design.
    """
    _require_admin(request)
    return analytics.snapshot(store, metrics.endpoint_counts())


@app.post("/api/admin/ban")
def admin_ban(body: BanRequest, request: Request) -> dict[str, Any]:
    """Ban an address. Operator action; requires the admin secret."""
    _require_admin(request)
    try:
        return abuse.ban(body.address, body.seconds, body.reason)
    except abuse.AbuseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/unban")
def admin_unban(body: BanRequest, request: Request) -> dict[str, Any]:
    """Lift a ban. Operator action; requires the admin secret."""
    _require_admin(request)
    return abuse.unban(body.address)


class DepositLimitRequest(BaseModel):
    # None clears the limit. Lowering and clearing are immediate; raising waits.
    limit: float | None = None


class ExclusionRequest(BaseModel):
    seconds: int


@app.get("/api/limits")
def limits_state(request: Request) -> dict[str, Any]:
    """The caller's responsible-gaming controls (plan item 11.3 / G3)."""
    return limits.state(_auth(request))


@app.post("/api/limits/deposit")
def limits_set_deposit(body: DepositLimitRequest, request: Request) -> dict[str, Any]:
    """Set a deposit ceiling. Lowering and clearing are immediate; raising waits."""
    try:
        return limits.set_deposit_limit(_auth(request), body.limit)
    except limits.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except limits.LimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/limits/self-exclude")
def limits_self_exclude(body: ExclusionRequest, request: Request) -> dict[str, Any]:
    """Exclude yourself from staked play. Cannot be lifted early."""
    try:
        return limits.self_exclude(_auth(request), body.seconds)
    except limits.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except limits.LimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/limits/cool-off")
def limits_cool_off(body: ExclusionRequest, request: Request) -> dict[str, Any]:
    """A short, immediate pause."""
    try:
        return limits.cool_off(_auth(request), body.seconds)
    except limits.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except limits.LimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class EligibilityRequest(BaseModel):
    # The client asserts it; the SERVER records it. An attestation the browser
    # keeps to itself is not a gate — see api/eligibility.py.
    ageConfirmed: bool


@app.get("/api/settlements")
def settlements(limit: int = 50) -> dict[str, Any]:
    """A PUBLIC, verifiable log of settled duels (plan item 11.3 / G11).

    Unauthenticated on purpose. The point of a settlement log is that a player —
    or anyone — can check that the server did not invent a winner, so requiring
    a login to read it would defeat it.

    Every entry carries the ORACLE SIGNATURE the contract accepted. That is what
    makes it verifiable rather than a claim: the same bytes can be checked
    against `PulsarEscrow.settleDuel` on-chain, so a log entry that does not
    verify is provably not a settlement.

    It exposes only what is already public on-chain: the match id, the two
    addresses, the winner, the times, the signature, and the settlement tx hash
    once a player has claimed. No balances, no emails, no history beyond the
    duel itself.
    """
    capped = max(1, min(int(limit), 200))
    out: list[dict[str, Any]] = []
    try:
        for snap in store.settled_matches(limit=capped):
            m = snap
            env = m.signed_settlement or {}
            out.append(
                {
                    "matchId": m.match_id,
                    "stake": m.stake,
                    "players": sorted(m.players.keys()),
                    "winner": m.winner,
                    "settledAt": m.settled_at,
                    "roundWins": env.get("roundWins", {}),
                    "forfeits": env.get("forfeits", {}),
                    # The proof, not a promise: this is what the contract checked.
                    "oracleAddress": env.get("oracleAddress", ""),
                    "signature": env.get("signature", ""),
                    "deadline": env.get("deadline"),
                    # Audit H-04 (2026-10-22): the lobby feed was reading
                    # `entryFee` from a collection the server never writes, so
                    # "LIVE ARENA FEED" was permanently empty — and had it ever
                    # rendered, every row would have said "win" because the
                    # client defaulted the missing field. The public feed is
                    # built from THIS log now, so it needs the per-duel facts:
                    # both validated times and the prize the winner received.
                    # These are already public on-chain (settleDuel's preimage
                    # contains both times; MatchSettled carries the prize).
                    "winnerTimeMs": env.get("winnerTimeMs"),
                    "loserTimeMs": env.get("loserTimeMs"),
                    # economy owns the fee constant (audit M20) — one definition, no drift.
                    "prize": economy.prize_in_units(
                        int(round(m.stake * 1_000_000)), 6
                    ) / 1_000_000,
                    "settlementTx": (m.signed_settlement or {}).get("settlementTx", ""),
                }
            )
    except Exception as exc:  # noqa: BLE001
        # A public endpoint must never 500. An empty log with a reason is honest;
        # a stack trace is not.
        return {"available": False, "reason": type(exc).__name__, "settlements": []}
    return {
        "available": True,
        # Published so a verifier knows which signer to check against.
        "oracleAddress": _oracle_address_or_none(),
        "count": len(out),
        "settlements": out,
    }


@app.post("/api/eligibility/confirm")
def eligibility_confirm(body: EligibilityRequest, request: Request) -> dict[str, Any]:
    """Record the caller's eligibility attestation, server-side."""
    address = _auth(request)
    if not body.ageConfirmed:
        raise HTTPException(status_code=400, detail="Eligibility was not confirmed")
    return {"ok": True, "confirmedAt": eligibility.record(address)}


@app.get("/api/eligibility")
def eligibility_status(request: Request) -> dict[str, Any]:
    """Whether this session may play for money."""
    address = _auth(request)
    return {"attested": eligibility.attested(address)}


@app.post("/api/queue")
def queue(body: QueueRequest, request: Request) -> dict[str, Any]:
    address = _auth_staked(request)
    _rl_check("queue", address, RL_QUEUE_MAX)
    # Plan item 11.3/G3: the player's OWN controls. Checked after eligibility
    # because it needs the stake, and because "you may not play at all" is a
    # different answer from "not at this stake".
    try:
        limits.require(address, body.stake)
    except limits.StoreUnavailable as exc:
        # H-02: a store outage must refuse staked play, not silently lift limits.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except limits.LimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Plan item 11.3/G6: bans and velocity. Last, because it is the only check
    # that can be about the PERSON rather than the request.
    try:
        abuse.require(address)
    except abuse.AbuseError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Audit C-01 (2026-10-22): `note_start` used to run HERE, before the
    # "already have a live match" early return below — so every QUEUE POLL of a
    # waiting player counted as a new duel. With VELOCITY_MAX_MATCHES=20 per
    # 10 minutes and the client polling every 2.5–10s, two searches (~11 polls
    # each) locked an honest player out for 15 minutes. A velocity limit that
    # fires on waiting is worse than none: it punishes exactly the behaviour it
    # is supposed to encourage and cannot distinguish a poller from a bot.
    #
    # The counter now moves ONLY when this request actually starts something:
    # a new waiting match or a join. Everything that returns an existing match
    # (the poll path) is free.
    if body.stake not in ALLOWED_STAKES:
        raise HTTPException(status_code=400, detail="Invalid stake")
    # Audit M27: a friend challenge is a reservation for one address. Validate
    # it here so a malformed value cannot create a match nobody can ever join.
    challenge_target = (body.opponent or "").strip().lower()
    if challenge_target:
        if not _is_address(challenge_target):
            raise HTTPException(status_code=400, detail="Invalid opponent address")
        if challenge_target == address.lower():
            raise HTTPException(status_code=400, detail="You cannot challenge yourself")
    # Audit H9: the sweep is maintenance, not part of answering this request —
    # it runs at most once per SWEEP_MIN_INTERVAL_SECONDS instead of on every
    # poll (three whole-collection scans per poll on the hottest endpoint).
    if _sweep_due():
        # Audit H8: the sweep no longer voids ACTIVE matches past their play
        # expiry — by then the grace window has passed, so they are forfeit
        # settlements, not abandonments. It hands them back; we finalize here.
        try:
            for due in store.sweep_expired():
                _finalize_if_due(due)
        except Exception as exc:
            # Never break matchmaking, but never hide it either (audit H9).
            _note_sweep_failure("sweep_expired", exc)
        # Audit #10 (item 5): refresh settled matches whose signed envelope
        # expired while both clients were offline (sweep-driven F-12 re-sign).
        try:
            _resign_stale_settlements()
        except Exception as exc:
            _note_sweep_failure("resign", exc)
    # Audit #8 F-13: durable idempotency — check Firestore for a live match
    # containing this address BEFORE enqueueing, so a re-poll that lands on a
    # different replica (or a recycled process) cannot mint an orphan match
    # the client might fund twice.
    live = store.player_live_match(address)
    if live is not None:
        if live.stake == body.stake:
            return live.public_view(for_address=address)
        # Audit M14: falling through to `enqueue` returned the SAME live match
        # (enqueue is idempotent), so a player who asked for 5 USDT silently got
        # their live 1 USDT match back and the UI showed a stake they never
        # chose. Refuse, and say why.
        raise HTTPException(
            status_code=409,
            detail=(
                f"You already have a live match at {live.stake:g} USDT. "
                f"Finish or leave it before queueing at {body.stake:g}."
            ),
        )
    # Audit C-01: this is the ONE point that can create or join a duel (the
    # live-match path returned above without reaching here), so it is the only
    # place a "start" is recorded.
    abuse.note_start(address)
    try:
        match = store.enqueue(address, body.stake, body.rttMs, challenge_target or None)
    except MatchError as exc:
        # L-10 (2026-10-22): the ping cap raises a DOMAIN error, and this handler
        # did not catch it — an over-latency connection got an unhandled 500
        # ("this is broken, do not retry") instead of the actionable 409 the
        # message contains. The client shows the detail; 5xx hides it.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Audit 2026-10-14 (found by the 1000-poller load run, plan item 10.3):
        # under contention the Firestore transaction exhausts its retries and
        # raises `ValueError: Failed to commit transaction in 5 attempts`. That
        # escaped as an **HTTP 500** — 157 of 157 queue requests failed that way
        # at 1000 concurrent pollers.
        #
        # A 500 tells the client "this is broken, do not retry". The truth is
        # the opposite: the request is fine and the store was busy, so the
        # honest answer is a RETRYABLE 503 with `Retry-After`. The client
        # already polls `/api/queue` while waiting, so it recovers on its own.
        if _is_store_contention(exc):
            raise HTTPException(
                status_code=503,
                detail="Matchmaking is busy — retry shortly.",
                headers={"Retry-After": "1"},
            ) from exc
        raise
    return match.public_view(for_address=address)


@app.get("/api/match/{match_id}")
def match_view(match_id: str, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        match = store.get(match_id)
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if address not in match.players:
        raise HTTPException(status_code=403, detail="Not a participant")
    # P0-fix (audit #2): settlement must never depend on a background worker.
    # Any participant polling the view finalizes a due match (completed, or
    # grace window passed) and immediately receives the authoritative status.
    _finalize_if_due(match)
    # Audit M10: the finalizer settles through `store.update`, whose
    # read-modify-write is ISOLATED on Firestore — the object read above does
    # not carry the settlement it just produced. Re-read so the view reflects
    # the status we just created; otherwise a poll that settled the match
    # answers "active", and the client's refresh recovery branches on that.
    try:
        match = store.get(match_id)
    except MatchError:
        pass
    return match.public_view(for_address=address)


# P0-fix — POST alias for GET /api/match/{id}. The client's generic `request`
# helper sent POST for every call including getMatch(), which 405'd here and
# cut the in-game refresh at ReactionGamePage. Both verbs share one handler so
# the client and the HTTP suite can never drift again.
@app.post("/api/match/{match_id}")
def match_view_post(match_id: str, request: Request) -> dict[str, Any]:
    return match_view(match_id, request)


@app.post("/api/round/commit")
def round_commit(body: CommitRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("commit", address, RL_COMMIT_MAX)
    try:
        # Audit-#3 fix: round mutations run inside a store transaction
        # (read-modify-write) so concurrent replicas cannot clobber rounds.
        # Audit-#5 gate: the escrow must hold BOTH stakes (read directly from
        # the chain) before any round is accepted — fail-closed.
        # Audit H10: the gate runs BEFORE store.update — it is network I/O and
        # must not be inside the lock.
        _gate_or_void(body.matchId)

        def _mutate(m: Any, eng: Any) -> None:
            eng.commit_intent(m, address, body.roundIndex, body.intentHash)
            return None

        store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.post("/api/round/target")
def round_target(body: TargetRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("round", address, RL_ROUND_MAX)  # audit #6 H7: hot endpoint
    try:
        # Same fail-closed deposit gate: revealing the target before the
        # escrow holds both stakes lets a stakeless client stall the duel.
        # Audit H10: gate outside the lock (network I/O).
        _gate_or_void(body.matchId)

        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            return eng.reveal_target(m, address, body.roundIndex)

        return store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/round/result")
def round_result(body: ResultRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("round", address, RL_ROUND_MAX)  # audit #6 H7: hot endpoint
    try:
        # Transactional submission: validated + stored atomically against the
        # authoritative document, then (when it completes the match) settled
        # and signed in the SAME transaction so no concurrent writer can
        # wedge the match between settle and sign.
        # Audit H10: gate outside the lock (network I/O).
        _gate_or_void(body.matchId)

        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            res = eng.submit_result(
                m, address, body.roundIndex, body.measuredMs, body.resultProof, rtt_ms=body.rttMs
            )
            if m.status == "active" and eng.match_completed(m):
                try:
                    result = eng.settle(m)
                    engine.apply_settlement_ratings(store, result)
                except MatchError:
                    result = None
                if result and result.get("status") == "settled":
                    res["settled"] = _attach_signed_envelope(m, result)
                    # Audit #11 H6: the NATURAL Bo3 completion usually lands
                    # here (the client requests /settle only to FETCH the
                    # stored envelope, which replays without ledgering) — so
                    # the economy ledger must be written in THIS path too.
                    #
                    # Audit H4: SIGNAL it, do not do it. `record_settlement`
                    # performs its own Firestore writes, so calling it from
                    # inside this mutate committed a ledger row independently of
                    # the match transaction — a rolled-back settlement left a
                    # ledger row behind. It runs after store.update returns.
                    res["_ledger_pending"] = True
            return res

        res = store.update(body.matchId, _mutate)
        if res.pop("_ledger_pending", False):
            _ledger_settlement(body.matchId)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return res


def _ledger_settlement(match_id: str) -> None:
    """Write the economy ledger AFTER the match transaction has committed.

    Audit H4: this used to run inside the store transaction, so a settlement
    that was rolled back still produced a ledger row. Reading the committed
    match here also means the ledger records what was actually persisted rather
    than the in-transaction object. `record_settlement` is idempotent
    (settlementId gate), so calling it on a replay is a no-op.
    """
    try:
        match = store.get(match_id)
    except MatchError:
        return
    if match.status == "settled":
        economy.record_settlement(match)


def _attach_signed_envelope(m: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Sign a settled result and attach the proof envelope to the match.
    Rollback-safe: a signing failure must never leave a settled-but-proofless
    match behind. Firestore rolls the transaction back on its own, but the
    in-memory object mutates IN PLACE — without this snapshot the match would
    be permanently wedged as 'settled' with no signature (audit #4)."""
    saved = (m.status, m.winner, m.settled_at, m.signed_settlement)
    try:
        # Audit #10 (item 5): pass the match so the signature deadline is
        # clamped to activation + contract MATCH_TIMEOUT.
        envelope = sign_settlement(result, matchish=m)
    except Exception:
        # Phase 6.1: a failing oracle means winners cannot claim, and from
        # outside it looks identical to a quiet period. Count it.
        metrics.note_signature(False)
        m.status, m.winner, m.settled_at, m.signed_settlement = saved
        raise
    metrics.note_signature(True)
    metrics.note_match_settled()
    envelope["roundWins"] = result.get("roundWins", {})
    # Audit 2026-10-13: the ledger reads `forfeits` off this envelope; without
    # the copy it recorded every duel as non-forfeit.
    envelope["forfeits"] = result.get("forfeits", {})
    m.signed_settlement = {"status": "settled", **envelope}
    return dict(m.signed_settlement)


def _settle_once(m: Any, eng: Any) -> dict[str, Any]:
    """Shared transactional settlement body: settle → sign → attach the proof
    envelope, persisted atomically by store.update().

    Idempotent — an already settled/void match is replayed, never re-signed —
    with ONE audit #8 F-12 exception: when the stored envelope's on-chain
    deadline has EXPIRED (the winner's client never managed to broadcast the
    tx within the 10-minute signature validity), the match is re-signed with
    a FRESH deadline + nonce. The server's result does not change; only the
    spendable proof is refreshed. Without this path a winner who closed the
    tab (or lost gas/RPC) forfeits the prize forever and the ledger keeps a
    "win + prize" that can never be collected."""
    if m.status == "settled" and m.signed_settlement:
        envelope = dict(m.signed_settlement)
        deadline = int(envelope.get("deadline", 0) or 0)
        if deadline and timebase.now() < deadline:
            return envelope  # still spendable — replay as-is
        # F-12 re-sign: result unchanged, fresh deadline + nonce.
        # Audit #10 (item 5): the re-sign is clamped to activation + contract
        # MATCH_TIMEOUT — past that horizon the duel is refundable and no
        # signature can pay (sign_settlement raises and the stale envelope
        # is returned; the refund path is the only money exit left).
        try:
            # Audit M7: the record is rebuilt by the ENGINE from the match it
            # owns and stamped, rather than hand-built here — a caller that can
            # build a dict with the right keys must not get a signature.
            fresh = sign_settlement(
                engine.settlement_record_for_resign(m),
                matchish=m,
            )
        except Exception:
            return envelope  # signing unavailable — return the stale envelope
        fresh["roundWins"] = envelope.get("roundWins", {})
        fresh["resigned"] = True
        m.signed_settlement = {"status": "settled", **fresh}
        return dict(m.signed_settlement)
    if m.status == "void":
        return {
            "status": "void",
            "reason": (
                "Match was voided — each stake refunds on-chain via "
                f"refundTimeoutMatch after the {int(REFUND_HORIZON_SECONDS // 60)}-minute escrow timeout."
            ),
        }
    try:
        result = eng.settle(m)
        engine.apply_settlement_ratings(store, result)
    except MatchError as e:
        # Audit M9: this body runs INSIDE `store.update`'s mutate — on Firestore,
        # inside a transaction. Raising the web framework's exception there
        # couples the persistence layer to HTTP and hands it an error it cannot
        # classify. Raise the engine's own error; the endpoint translates it.
        raise MatchError(str(e)) from e
    if result.get("status") == "settled":
        envelope = _attach_signed_envelope(m, result)
        # Audit H4: the ledger write moved OUT of this mutate. It used to run
        # here, inside the store transaction, so a rolled-back settlement still
        # produced a ledger row. The callers now ledger after store.update
        # returns (see _ledger_settlement).
        return envelope
    return {"status": "void", "reason": result.get("reason", "stakes refund")}


def _finalize_if_due(match: Any) -> None:
    """Lazy finalizer: when a match is complete (both players finished, or the
    grace window passed making missing rounds forfeits), settle+sign it.
    Called from read paths so settlement never depends on a background worker.
    Idempotent: an already-settled/void match is left untouched."""
    if match.status != "active" or not match_completed(match):
        return
    try:
        store.update(match.match_id, _settle_once)
        _ledger_settlement(match.match_id)
    except MatchError as exc:
        # Audit M9: the settlement body raises only domain errors now.
        # Audit 8.15: it used to be swallowed silently, so a match that could
        # never settle looked exactly like a quiet period. Count it and surface
        # it on /api/health.
        _note_sweep_failure("finalize_if_due", exc)


def _resign_stale_settlements() -> None:
    """Audit #10 (item 5): sweep-driven re-sign of expired proofs.

    The F-12 re-sign path used to run ONLY when a participant polled /settle —
    if both players closed their tabs, the match stayed 'settled' with an
    expired envelope and the winner's prize was unspendable until someone
    happened to call the endpoint again. The re-sign is a pure server-side
    state refresh (result unchanged, fresh deadline+nonce), so it belongs in
    the same lazy sweep that /api/queue already runs: ANY authenticated queue
    poll (matchmaking traffic — the busiest path) refreshes every settled
    match whose envelope is stale but whose on-chain duel can still pay
    (inside MATCH_TIMEOUT). Sweep is best-effort: failures never block queueing."""
    try:
        # Audit #11 C2: iterating store.memory.matches scanned only THIS
        # replica's cache — on Firestore, matches settled on other replicas
        # were never re-signed (both players close tabs → prize unspendable
        # until luck re-routes traffic). The durable sweep reads the settled
        # COLLECTION itself, so every replica sees the full stale set. The
        # memory-cache pass stays as the zero-cost fast path.
        for mid, m in list(getattr(store.memory, "matches", {}).items()):
            if m.status != "settled" or not m.signed_settlement:
                continue
            deadline = int(m.signed_settlement.get("deadline", 0) or 0)
            if not deadline or timebase.now() < deadline:
                continue  # still spendable / never signed
            if timebase.now() >= engine.settlement_deadline(m):
                continue  # past the on-chain horizon — only refund applies
            try:
                store.update(mid, _settle_once)
                _ledger_settlement(mid)
            except MatchError as exc:
                # Audit M9: the settlement body raises only domain errors now.
                # Audit 8.15: counted, not swallowed — a re-sign that keeps
                # failing means a winner's prize stays unspendable, and that must
                # be visible on /api/health rather than look like a quiet period.
                _note_sweep_failure("resign_memory", exc)
        for m in store.sweep_stale_settlements():
            deadline = int((m.signed_settlement or {}).get("deadline", 0) or 0)
            if deadline and timebase.now() >= engine.settlement_deadline(m):
                continue  # past the on-chain horizon — only refund applies
            try:
                store.update(m.match_id, _settle_once)
                _ledger_settlement(m.match_id)
            except MatchError as exc:
                # Audit M9 + 8.15: counted, not swallowed.
                _note_sweep_failure("resign_durable", exc)
    except Exception as exc:
        # Audit 8.15: the outer guard stays (a sweep must never break
        # matchmaking) but it no longer hides the reason.
        _note_sweep_failure("resign_sweep", exc)


@app.post("/api/match/{match_id}/settle")
def settle_match(match_id: str, request: Request) -> dict[str, Any]:
    address = _auth(request)
    # Audit #10 (item 7): settle is a transactional Firestore read-modify-write
    # with signature minting — an unauthenticated flood would be both a Firestore
    # cost amplifier (and NOT free on the free tier) and a signature-mint
    # DoS vector. 10 calls/min per address is far above any legitimate polling
    # cadence (the client settles once, then replays).
    _rl_check("settle", address, RL_SETTLE_MAX)
    try:
        match = store.get(match_id)
        if address not in match.players:
            raise HTTPException(status_code=403, detail="Not a participant")
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # P0-fix — single-flight settlement, now CROSS-REPLICA (audit #3): the
    # settle→sign→persist sequence runs inside a store transaction, so two
    # players on different backend replicas can no longer produce two
    # different signatures; the transaction serializes them and the loser of
    # the race replays the ONE stored proof.
    try:
        envelope = store.update(match_id, _settle_once)
    except MatchError as e:
        # Audit M9: the domain error raised by the settlement body maps to the
        # same 409 the store used to raise itself. The translation lives here,
        # at the HTTP boundary, instead of inside the persistence layer.
        raise HTTPException(status_code=409, detail=str(e))
    _ledger_settlement(match_id)
    return envelope


@app.post("/api/match/{match_id}/claim")
def claim_match(match_id: str, body: ClaimRequest, request: Request) -> dict[str, Any]:
    # Audit #10 (item 7): every call pays for an RPC eth_getTransactionReceipt
    # — an unauthenticated flood was a cheap RPC/infura-paid DoS. 10/min per
    # address is generous for a claim+retry flow.
    _rl_check("claim", _auth(request), RL_CLAIM_MAX)
    """C5 + audit #8 F-04 — VERIFIED on-chain claim persistence.

    The tx hash used to be stored verbatim (any hex string became
    "onChain: true" forever). Now the server fetches the receipt from the
    RPC and only records the claim when the tx REALLY settled THIS match:
      - receipt exists and succeeded,
      - `to` == the configured escrow,
      - a MatchSettled(matchId, winner, ...) event log for THIS match id
        (sha256 convention) with winner == the claimer.
    A participant may still POST early (their tx may need a moment to be
    mined); the response says onChainProof=false in that case and the client
    can retry. Nothing unverifiable is ever persisted."""
    address = _auth(request)
    try:
        match = store.get(match_id)
        if address not in match.players:
            raise HTTPException(status_code=403, detail="Not a participant")
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))
    winner = (getattr(match, "winner", "") or "").lower()
    # Audit M11: the on-chain check below proves the TX settled this match and
    # paid `winner` — it says nothing about who is CALLING. Without this, the
    # loser could POST a claim and have `onChain: true` recorded against the
    # match, so the ledger says the wrong player claimed.
    if not winner or address.lower() != winner:
        raise HTTPException(status_code=403, detail="Only the winner may claim")
    verified = onchain.verify_settlement_tx(body.txHash, match_id, winner)
    if not verified:
        return {
            "ok": False,
            "onChainProof": False,
            "reason": (
                "Transaction not verified as a settlement of this match yet — "
                "it must be mined, target the escrow, and emit MatchSettled "
                "for this match with the winner as claimer. Retry after the tx confirms."
            ),
        }
    recorded = economy.record_claim(match_id, winner, body.txHash)
    return {"ok": recorded, "onChainProof": recorded}


# --- Audit #8 F-08 — username ownership is SERVER-ENFORCED -------------------
#
# The old flow let any client write usernames/{name} directly with any
# address (rules only checked the address format) — free namespace squatting
# and identity theft. Now the claim runs HERE, authenticated by the caller's
# SIWE session, inside an idempotent transaction:
#   - the claimed doc must be free OR already owned by the caller,
#   - the caller's previous username is released in the same transaction.

USERNAME_MIN_LEN = 3
USERNAME_MAX_LEN = 20
USERNAME_PATTERN = "^[a-zA-Z0-9_]+$"
USERNAME_RESERVED = {
    "admin", "pulsar", "official", "system", "treasury", "moderator",
    "support", "bot", "oracle", "escrow",
}


class UsernameRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


def _clean_username(raw: str) -> str:
    import re as _re

    tag = raw.strip()
    if not (USERNAME_MIN_LEN <= len(tag) <= USERNAME_MAX_LEN):
        raise HTTPException(status_code=400, detail="Username must be 3-20 characters")
    if not _re.match(USERNAME_PATTERN, tag):
        raise HTTPException(status_code=400, detail="Only letters, numbers and underscores are allowed")
    if tag.lower() in USERNAME_RESERVED:
        raise HTTPException(status_code=400, detail=f'"{tag}" is a reserved system name')
    return tag


@app.post("/api/username/claim")
def username_claim(body: UsernameRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("username", address, 10)
    tag = _clean_username(body.username)
    normalized = tag.lower()
    # Audit CRITICAL-1: `getattr(store, "_fs_store")` is a MODULE attribute that
    # never exists (`_fs_store` is an instance attribute of DurableMatchStore),
    # so this endpoint answered 503 for every caller in production.
    import store as _store_mod

    db = _store_mod.durable_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Username registry requires the durable store (Firestore)")

    try:
        from google.cloud.firestore_v1.base_transaction import transactional  # type: ignore

        @transactional
        def _claim(tx) -> dict[str, Any]:
            registry = db.collection("usernames")
            users = db.collection("users")
            doc_ref = registry.document(normalized)
            snap = doc_ref.get(transaction=tx)
            if snap.exists:
                owner = (snap.to_dict() or {}).get("address", "").lower()
                if owner != address:
                    raise HTTPException(status_code=409, detail=f'Username "{tag}" is already taken')
                # Already ours — idempotent success.
                return {"ok": True, "cleanTag": tag, "alreadyOwned": True}

            # Release the caller's previous username (atomic, same tx).
            user_snap = users.document(address).get(transaction=tx)
            old_tag = ((user_snap.to_dict() or {}).get("playerId") or "").strip()
            if old_tag and old_tag.lower() != normalized:
                old_ref = registry.document(old_tag.lower())
                old_snap = old_ref.get(transaction=tx)
                if old_snap.exists and (old_snap.to_dict() or {}).get("address", "").lower() == address:
                    tx.delete(old_ref)

            doc_ref.create({"username": normalized, "tag": tag, "address": address})
            users.document(address).set({"playerId": tag}, merge=True)
            return {"ok": True, "cleanTag": tag, "alreadyOwned": False}

        result = _claim(db.transaction())
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=409, detail=f"Username claim failed: {e}")


@app.get("/api/username/{name}")
def username_lookup(name: str, request: Request) -> dict[str, Any]:
    # Must hold a session: the registry is the server's, and the response must
    # not be an anonymous enumeration oracle.
    _auth(request)
    # Audit #11 H3: session auth alone does not stop name enumeration (a
    # script can hold one valid session). IP-keyed cap keeps the check cheap
    # for the UI (a couple of calls per claim) while throttling crawlers.
    _rl_check_ip("username_lookup", request, RL_USERNAME_LOOKUP_MAX)
    normalized = name.strip().lower()
    # Audit CRITICAL-1: `getattr(store, "_fs_store")` is a MODULE attribute that
    # never exists (`_fs_store` is an instance attribute of DurableMatchStore),
    # so this endpoint answered 503 for every caller in production.
    import store as _store_mod

    db = _store_mod.durable_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Username registry requires the durable store (Firestore)")
    snap = db.collection("usernames").document(normalized).get()
    if not snap.exists:
        return {"available": True, "username": normalized}
    owner = ((snap.to_dict() or {}).get("address") or "").lower()
    # Audit M12 (2026-10-13): this returned `owner` — the wallet address of
    # whoever holds the name. The finding was marked fixed in phase 6.10 and was
    # not: any session holder could enumerate names and map them to addresses.
    # The caller learns only whether the name is theirs.
    caller = _auth(request)
    if owner and owner == caller.lower():
        return {"available": True, "username": normalized, "alreadyOwned": True}
    return {"available": False, "username": normalized, "taken": True}


@app.get("/api/player/{address}/stats")
def player_stats(address: str, request: Request) -> dict[str, Any]:
    """Server-authoritative progression for a player (audit M31).

    Wins/XP/level/streak used to live entirely in the client's localStorage:
    any player could edit them, and the documented streak bonus could never
    fire because `winStreak` was never passed to the XP calculation. This is
    the ledger's view of the same numbers.

    When the ledger is unavailable the response says `available: false` instead
    of reporting zeros — a zero that means "no data" and a zero that means "no
    wins" must not look the same to the client.
    """
    caller = _auth(request)
    addr = (address or "").strip().lower()
    if not _is_address(addr):
        raise HTTPException(status_code=400, detail="Invalid address")
    # Keyed by the CALLER, not the requested address: keying on the target let
    # one caller spend a victim's budget and 429 that victim's own reads.
    _rl_check("player_stats", caller, RL_PLAYER_STATS_MAX)
    stats = economy.player_stats(addr)
    if stats is None:
        return {"available": False}
    return {"available": True, **stats}


@app.get("/api/challenges")
def list_challenges(request: Request) -> dict[str, Any]:
    """Challenges waiting for the CALLER (audit M27 closure).

    A reservation the target cannot discover is a duel that never happens: the
    challenged player used to learn about it only by queueing for something
    else. This is the read side of `POST /api/queue {opponent}`.
    """
    address = _auth(request)
    _rl_check("challenges", address, RL_CHALLENGES_MAX)
    try:
        challenges = store.pending_challenges(address)
    except Exception as exc:
        _note_sweep_failure("pending_challenges", exc)
        return {"available": False, "challenges": []}
    return {"available": True, "challenges": challenges}
