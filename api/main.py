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
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auth import issue_nonce, issue_session, verify_session  # verify_session used by _auth
from match_engine import MatchError, match_completed
from oracle import sign_settlement
from store import create_store, install_persistence

app = FastAPI(title="PULSAR Game Server", version="1.1.1")

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

# Serializes the settle→sign→persist sequence (see settle_match).
_settle_lock = threading.Lock()

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
    message: str
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]+$")


class QueueRequest(BaseModel):
    stake: float


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
    message = (
        f"{domain} wants you to sign in with your Polygon account:\n"
        f"{body.address.lower()}\n"
        "\n"
        "Prove you own this wallet. This signature grants no permission to move funds or spend tokens.\n"
        "\n"
        f"URI: https://{domain}\n"
        "Version: 1\n"
        "Chain ID: 137\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}\n"
    )
    return {"nonce": nonce, "message": message}


@app.post("/api/auth/verify")
def auth_verify(body: VerifyRequest, request: Request) -> dict[str, str]:
    domain = _request_domain(request)
    from auth import verify_siwe

    recovered = verify_siwe(body.message, body.signature, domain)
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
        match = store.get(body.matchId)
        commit_intent(match, address, body.roundIndex, body.intentHash)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.post("/api/round/target")
def round_target(body: TargetRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        match = store.get(body.matchId)
        return reveal_target(match, address, body.roundIndex)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/round/result")
def round_result(body: ResultRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        match = store.get(body.matchId)
        res = submit_result(match, address, body.roundIndex, body.measuredMs, body.resultProof)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # P0-fix (audit #2/#3): when the last round lands, settle+sign
    # IMMEDIATELY under the settle lock. Nobody can race a premature
    # settle and the very request that completes the match carries the
    # oracle envelope back to its caller.
    if match.status == "active" and match_completed(match):
        with _settle_lock:
            if match.status == "active":
                try:
                    result = settle(match)
                except MatchError:
                    result = None
                if result:
                    res["settled"] = _sign_and_persist(result, match)
    return res


def _sign_and_persist(result: dict[str, Any], match: Any) -> dict[str, Any]:
    """Common settlement tail: sign settled output → attach the proof envelope
    → persist IN THE SAME PASS (the persistence hook inside settle() runs
    before the signature exists). Must be called under _settle_lock."""
    if result.get("status") == "settled":
        envelope = sign_settlement(result)
        envelope["roundWins"] = result.get("roundWins", {})
        settled = {"status": "settled", **envelope}
        match.signed_settlement = dict(settled)
        store.put(match)
        return settled
    store.put(match)  # void — persist so the refundable state is durable
    return {"status": "void", "reason": result.get("reason", "stakes refund")}


def _finalize_if_due(match: Any) -> None:
    """Lazy finalizer: when a match is complete (both players finished, or the
    grace window passed making missing rounds forfeits), settle+sign it.
    Called from read paths so settlement never depends on a background worker.
    Idempotent: an already-settled/void match is left untouched."""
    if match.status != "active" or not match_completed(match):
        return
    with _settle_lock:
        if match.status != "active":
            return
        try:
            result = settle(match)
        except MatchError:
            return
        _sign_and_persist(result, match)


@app.post("/api/match/{match_id}/settle")
def settle_match(match_id: str, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        match = store.get(match_id)
        if address not in match.players:
            raise HTTPException(status_code=403, detail="Not a participant")
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # P0-fix — single-flight settlement. Two concurrent requests both saw an
    # active match and each called settle()+sign_settlement(), producing two
    # different signatures over different nonces; the contract's replay
    # binding accepts only the first one on-chain, so the other player's proof
    # would revert. The lock makes settle→sign→persist atomic; any later
    # caller (including the other client) hits the idempotent replay branch
    # and receives the ONE stored proof.
    with _settle_lock:
        if match.status == "settled" and match.signed_settlement:
            return dict(match.signed_settlement)
        if match.status == "void":
            return {"status": "void", "reason": "Match was voided — stakes are refundable on-chain."}

        try:
            result = settle(match)
        except MatchError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return _sign_and_persist(result, match)
