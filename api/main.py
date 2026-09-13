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

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import EXPECTED_CHAIN_ID, issue_nonce, issue_session, verify_session
from match_engine import MatchError, match_completed
from oracle import sign_settlement
from store import create_store, install_persistence

app = FastAPI(title="PULSAR Game Server", version="1.1.1")

_rate_lock = threading.Lock()
_rate_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_limits(request: Request, call_next: Any):
    """Bound request bodies and obvious per-IP abuse.

    Production ingress should enforce a distributed limit as well; this local
    guard prevents a single worker from accepting unbounded SIWE/result spam.
    """
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > 32_768:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        group = "auth" if request.url.path.startswith("/api/auth/") else "api"
        limit = 30 if group == "auth" else 300
        now = time.monotonic()
        key = (ip, group)
        with _rate_lock:
            window = _rate_windows[key]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= limit:
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            window.append(now)
    return await call_next(request)

# P0-fix — CORS. The frontend (static hosting) and this API are commonly on
# different origins (docs/DEPLOYMENT.md deployment topology), so browsers send
# preflights for the JSON + Authorization requests the client makes. Without
# this middleware every cross-origin call died in the browser. Origins are
# env-configured. Default-deny is intentional: a malicious site must not be
# allowed to drive SIWE + wager API calls from a victim's browser. Same-origin
# deployments need no CORS entry; split frontend/API deployments must list the
# exact frontend origins explicitly.
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
]
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



@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "pulsar-game-server",
        "rounds": ROUNDS,
        "matchStore": store.backend_name,  # honest visibility for ops
    }


def _request_domain(request: Request) -> str:
    override = os.environ.get("ALLOWED_DOMAIN", "")
    if override:
        return override
    return request.headers.get("host", "localhost")


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
    message: str = Field(min_length=1, max_length=4096)
    signature: str = Field(min_length=132, max_length=132, pattern=r"^0x[0-9a-fA-F]+$")


class QueueRequest(BaseModel):
    stake: float


class UsernameRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")


class CommitRequest(BaseModel):
    matchId: str
    roundIndex: int
    intentHash: str = Field(pattern=r"^0x[0-9a-f]{64}$")


class TargetRequest(BaseModel):
    matchId: str
    roundIndex: int


class ResultRequest(BaseModel):
    matchId: str
    roundIndex: int
    measuredMs: float = Field(gt=0, le=5000)
    # P0-fix (audit #2): unforgeable per-player proof issued at reveal. Without
    # it the stored result was disconnected from its commit (any 90ms claim
    # after any commit was accepted).
    resultProof: str = ""


@app.post("/api/auth/nonce")
def auth_nonce(body: NonceRequest, request: Request) -> dict[str, str]:
    domain = _request_domain(request)
    nonce = issue_nonce(body.address, domain)
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    expires = now + __import__('datetime').timedelta(minutes=5)
    message = (
        f"{domain} wants you to sign in with your Polygon account:\n"
        f"{body.address.lower()}\n"
        "\n"
        "Prove you own this wallet. This signature grants no permission to move funds or spend tokens.\n"
        "\n"
        f"URI: https://{domain}\n"
        "Version: 1\n"
        f"Chain ID: {EXPECTED_CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {now.isoformat()}\n"
        f"Expiration Time: {expires.isoformat()}\n"
    )
    return {"nonce": nonce, "message": message}


@app.post("/api/auth/verify")
def auth_verify(body: VerifyRequest, request: Request) -> dict[str, str]:
    domain = _request_domain(request)
    from auth import verify_siwe

    recovered = verify_siwe(
        body.message,
        body.signature,
        domain,
        consume_nonce=store.consume_auth_nonce,
    )
    if not recovered:
        raise HTTPException(status_code=401, detail="SIWE verification failed")
    return {"token": issue_session(recovered), "address": recovered}


@app.post("/api/queue")
def queue(body: QueueRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    if body.stake not in ALLOWED_STAKES:
        raise HTTPException(status_code=400, detail="Invalid stake")
    store.sweep_expired()
    match = store.enqueue(address, body.stake)
    return match.public_view(for_address=address)


@app.post("/api/queue/cancel")
def cancel_queue(request: Request) -> dict[str, Any]:
    """Release a waiting queue slot. A pairing race fails safe: once a second
    player joined, the active match is returned and is never cancelled."""
    address = _auth(request)
    match = store.cancel_waiting(address)
    if match is None:
        return {"cancelled": True, "match": None}
    return {
        "cancelled": match.status == "void",
        "match": match.public_view(for_address=address),
    }


@app.post("/api/profile/username")
def claim_username(body: UsernameRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    reserved = {"admin", "pulsar", "official", "system", "treasury", "moderator", "support", "bot", "oracle", "escrow"}
    if body.username.lower() in reserved:
        raise HTTPException(status_code=400, detail="Reserved username")
    if not store.claim_username(address, body.username):
        raise HTTPException(status_code=409, detail="Username is already taken")
    return {"success": True, "username": body.username}


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
    match = store.get(match_id)  # finalization replaces the transactional snapshot
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
    try:
        # Audit-#3 fix: round mutations run inside a store transaction
        # (read-modify-write) so concurrent replicas cannot clobber rounds.
        def _mutate(m: Any, eng: Any) -> None:
            eng.commit_intent(m, address, body.roundIndex, body.intentHash)

        store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.post("/api/round/target")
def round_target(body: TargetRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            return eng.reveal_target(m, address, body.roundIndex)

        return store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/round/result")
def round_result(body: ResultRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        # Transactional submission: validated + stored atomically against the
        # authoritative document, then (when it completes the match) settled
        # and signed in the SAME transaction so no concurrent writer can
        # wedge the match between settle and sign.
        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            res = eng.submit_result(m, address, body.roundIndex, body.measuredMs, body.resultProof)
            if m.status == "active" and eng.match_completed(m):
                try:
                    result = eng.settle(m)
                except MatchError:
                    result = None
                if result and result.get("status") == "settled":
                    envelope = sign_settlement(result)
                    envelope["roundWins"] = result.get("roundWins", {})
                    envelope["loser"] = result.get("loser", "")
                    envelope["stake"] = result.get("stake", 0)
                    m.signed_settlement = {"status": "settled", **envelope}
                    res["settled"] = m.signed_settlement
            return res

        res = store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(res.get("settled"), dict):
        _record_settlement_best_effort(res["settled"])
    return res


def _settle_once(m: Any, eng: Any) -> dict[str, Any]:
    """Shared transactional settlement body: settle → sign → attach the proof
    envelope, persisted atomically by store.update(). Idempotent — an already
    settled/void match is replayed, never re-signed."""
    if m.status == "settled" and m.signed_settlement:
        existing = dict(m.signed_settlement)
        if int(existing.get("deadline", 0)) > int(time.time()) + 30:
            return existing
        # Expired proofs are safe to replace: the contract rejects the old
        # deadline, and a new nonce/signature lets a failed wallet claim retry.
        refreshed = sign_settlement(
            {
                "status": "settled",
                "matchId": existing["matchId"],
                "winner": existing["winner"],
                "winnerTimeMs": existing["winnerTimeMs"],
                "loserTimeMs": existing["loserTimeMs"],
                "validatedTimes": existing["validatedTimes"],
            }
        )
        refreshed["roundWins"] = existing.get("roundWins", {})
        refreshed["loser"] = existing.get("loser", "")
        refreshed["stake"] = existing.get("stake", 0)
        m.signed_settlement = {"status": "settled", **refreshed}
        return dict(m.signed_settlement)
    if m.status == "void":
        return {"status": "void", "reason": "Match was voided — stakes are refundable on-chain."}
    try:
        result = eng.settle(m)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if result.get("status") == "settled":
        envelope = sign_settlement(result)
        envelope["roundWins"] = result.get("roundWins", {})
        envelope["loser"] = result.get("loser", "")
        envelope["stake"] = result.get("stake", 0)
        m.signed_settlement = {"status": "settled", **envelope}
        return dict(m.signed_settlement)
    return {"status": "void", "reason": result.get("reason", "stakes refund")}


def _finalize_if_due(match: Any) -> None:
    """Lazy finalizer: when a match is complete (both players finished, or the
    grace window passed making missing rounds forfeits), settle+sign it.
    Called from read paths so settlement never depends on a background worker.
    Idempotent: an already-settled/void match is left untouched."""
    if match.status != "active" or not match_completed(match):
        return
    try:
        result = store.update(match.match_id, _settle_once)
        if result.get("status") == "settled":
            _record_settlement_best_effort(result)
    except (MatchError, HTTPException):
        pass


def _record_settlement_best_effort(result: dict[str, Any]) -> None:
    """Public stats must never block delivery of an already-committed proof."""
    try:
        store.record_settlement(result)
    except Exception:
        pass


@app.post("/api/match/{match_id}/settle")
def settle_match(match_id: str, request: Request) -> dict[str, Any]:
    address = _auth(request)
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
    result = store.update(match_id, _settle_once)
    if result.get("status") == "settled":
        _record_settlement_best_effort(result)
    return result
