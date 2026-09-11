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
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from auth import issue_nonce, issue_session, verify_session  # verify_session used by _auth
from match_engine import MatchError
from oracle import sign_settlement
from store import create_store, install_persistence

app = FastAPI(title="PULSAR Game Server", version="1.1.0")

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
    return match.public_view(for_address=address)


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
        return submit_result(match, address, body.roundIndex, body.measuredMs)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/match/{match_id}/settle")
def settle_match(match_id: str, request: Request) -> dict[str, Any]:
    address = _auth(request)
    try:
        match = store.get(match_id)
        if address not in match.players:
            raise HTTPException(status_code=403, detail="Not a participant")
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Idempotent: when both clients race to settle, the first signs and the
    # second receives the SAME oracle signature (never a second signature over
    # a new nonce, which would break the contract's replay binding).
    if match.status == "settled" and match.signed_settlement:
        return dict(match.signed_settlement)

    try:
        result = settle(match)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if result.get("status") == "settled":
        result = sign_settlement(result)
        match.signed_settlement = dict(result)
    return result
