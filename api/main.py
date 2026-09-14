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
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import auth as _auth_module
import economy
from auth import issue_nonce, issue_session, verify_session, verify_siwe
from match_engine import MatchError, match_completed
from oracle import sign_settlement
from store import create_store, install_persistence

# Single source of truth for the chain this deployment runs on. The SIWE
# statement, the oracle digest and the client (VITE_CHAIN_ID → CHAIN.chainId)
# must all agree — the audit regression was main.py hardcoding 137 while
# auth.py verified against 80002, so signing the server's OWN message 401'd.
import onchain
from auth import EXPECTED_CHAIN_ID as _CHAIN_ID
from auth import NONCE_WINDOW_SECONDS as _NONCE_WINDOW

# --- Distributed rate limiting (audit #5, item 8) ----------------------------
# The audit asked for distributed limiting; there was NO limiter at all. This
# one is Firestore-backed (any replica sees the same window) with a per-process
# fallback for memory mode. Applied only to expensive/abusable endpoints.
_rl_lock = threading.Lock()
_rl_window: dict[str, list[float]] = {}
RL_WINDOW_SECONDS = 60.0
RL_QUEUE_MAX = 40        # queue calls per minute per address (audit #6 C3:
                         # the client's 2.5s poll = 24/min; 20/min kicked
                         # honest waiting players out of matchmaking at t≈50s)
RL_COMMIT_MAX = 40       # round commits per minute per address
RL_AUTH_MAX = 10         # SIWE handshakes per minute per address
RL_VERIFY_MAX = 30       # SIWE verifications per minute per IP (ecrecover is
                         # CPU work; unthrottled it was a cheap DoS surface)
RL_ROUND_MAX = 60        # target reveals + result submissions per minute per
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
    otherwise the in-process fallback."""
    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    _rl_check(bucket, ip, limit)


def _rl_check(bucket: str, address: str, limit: int) -> None:
    """Count one hit for (bucket, address) and refuse when over `limit`.

    Firestore mode uses a transactional read-modify-write on a rate_limits
    document so EVERY replica enforces the SAME window; memory mode is
    per-process. A Firestore outage degrades to in-process limiting instead of
    taking the endpoint down (fail-open for availability, never for money —
    the deposit gate below is fail-closed)."""
    fs = getattr(store, "_fs_store", None)
    if fs is not None:  # audit #7 R3: decoupled from onchain.escrow_configured()
        try:
            doc = fs.db.collection("rate_limits").document(f"rl:{bucket}:{address.lower()}")
            now_ms = int(time.time() * 1000)
            window_ms = int(RL_WINDOW_SECONDS * 1000)

            def _incr(txn: Any) -> int:
                snap = doc.get(transaction=txn)
                d = snap.to_dict() or {"count": 0, "reset_at": 0}
                if now_ms >= int(d.get("reset_at", 0)):
                    d = {"count": 1, "reset_at": now_ms + window_ms}
                else:
                    d = {"count": int(d.get("count", 0)) + 1, "reset_at": int(d["reset_at"])}
                txn.set(doc, d)
                return int(d["count"])

            txn = fs.db.transaction()
            count = _incr(txn)  # plain callable: Firestore retries conflicts itself
            if count > limit:
                raise _rate_limited((int(d["reset_at"]) - now_ms) / 1000.0)
            return
        except HTTPException:
            raise
        except Exception:
            pass  # Firestore hiccup → fall through to in-process limiting
    with _rl_lock:
        key = f"{bucket}:{address.lower()}"
        now = time.time()
        hits = [t for t in _rl_window.get(key, []) if now - t < RL_WINDOW_SECONDS]
        hits.append(now)
        _rl_window[key] = hits
        if len(hits) > limit:
            raise _rate_limited(RL_WINDOW_SECONDS - (now - hits[0]))


# Joiner-deposit timeout (audit #5, item 3): if the joiner's stake never lands
# on-chain within this window after matchmaking, the match is voided so the
# creator can refund (refundTimeoutMatch) instead of being locked for the
# 30-minute on-chain refund horizon.
DEPOSIT_TIMEOUT_SECONDS = 300.0


def _verify_deposits_or_void(m: Any) -> dict[str, Any] | None:
    """On-chain deposit gate for round actions. Returns None to proceed.

    Fail-CLOSED: when escrow mode is configured but the deposit state cannot
    be read, rounds are refused — a custom client that never stakes must not
    be able to grief an honest opponent's locked deposit. Also voids the
    server-side match when the joiner's deposit never arrives (the creator
    then gets an explicit 'refund on-chain' signal instead of a stalled duel)."""
    if not onchain.escrow_configured():
        return None  # practice / unconfigured dev — gate inactive
    status = onchain.duel_status(m.match_id)
    if status == onchain.STATUS_ACTIVE:
        return None  # both stakes locked — play on
    if status == onchain.STATUS_CREATED and time.time() - m.created_at > DEPOSIT_TIMEOUT_SECONDS:
        m.status = "void"
        # H4 — honest money-UX: the contract only releases refunds at
        # createdAt + MATCH_TIMEOUT (30 min). Saying "refundable now" sends
        # players into a revert for ~25 minutes. State the real window.
        return {
            "void": True,
            "reason": (
                "Opponent stake deposit timed out — the match is void. The "
                "creator's stake becomes refundable on-chain via "
                "refundTimeoutMatch after the 30-minute escrow timeout."
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
        window * _NONCE_WINDOW, tz=_dt.timezone.utc
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


class ClaimRequest(BaseModel):
    txHash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    signature: str = ""


@app.post("/api/auth/nonce")
def auth_nonce(body: NonceRequest, request: Request) -> dict[str, str]:
    _rl_check("auth", body.address, RL_AUTH_MAX)
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


@app.post("/api/queue")
def queue(body: QueueRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("queue", address, RL_QUEUE_MAX)
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
    _rl_check("commit", address, RL_COMMIT_MAX)
    try:
        # Audit-#3 fix: round mutations run inside a store transaction
        # (read-modify-write) so concurrent replicas cannot clobber rounds.
        # Audit-#5 gate: the escrow must hold BOTH stakes (read directly from
        # the chain) before any round is accepted — fail-closed.
        def _mutate(m: Any, eng: Any) -> dict[str, Any] | None:
            gate = _verify_deposits_or_void(m)
            if gate:
                return gate
            eng.commit_intent(m, address, body.roundIndex, body.intentHash)
            return None

        gate = store.update(body.matchId, _mutate)
        if gate and gate.get("void"):
            raise HTTPException(status_code=409, detail=gate["reason"])
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
        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            gate = _verify_deposits_or_void(m)
            if gate:
                raise MatchError(gate["reason"])
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
        def _mutate(m: Any, eng: Any) -> dict[str, Any]:
            gate = _verify_deposits_or_void(m)
            if gate:
                raise MatchError(gate["reason"])
            res = eng.submit_result(m, address, body.roundIndex, body.measuredMs, body.resultProof)
            if m.status == "active" and eng.match_completed(m):
                try:
                    result = eng.settle(m)
                except MatchError:
                    result = None
                if result and result.get("status") == "settled":
                    res["settled"] = _attach_signed_envelope(m, result)
            return res

        res = store.update(body.matchId, _mutate)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return res


def _attach_signed_envelope(m: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Sign a settled result and attach the proof envelope to the match.
    Rollback-safe: a signing failure must never leave a settled-but-proofless
    match behind. Firestore rolls the transaction back on its own, but the
    in-memory object mutates IN PLACE — without this snapshot the match would
    be permanently wedged as 'settled' with no signature (audit #4)."""
    saved = (m.status, m.winner, m.settled_at, m.signed_settlement)
    try:
        envelope = sign_settlement(result)
    except Exception:
        m.status, m.winner, m.settled_at, m.signed_settlement = saved
        raise
    envelope["roundWins"] = result.get("roundWins", {})
    m.signed_settlement = {"status": "settled", **envelope}
    return dict(m.signed_settlement)


def _settle_once(m: Any, eng: Any) -> dict[str, Any]:
    """Shared transactional settlement body: settle → sign → attach the proof
    envelope, persisted atomically by store.update(). Idempotent — an already
    settled/void match is replayed, never re-signed."""
    if m.status == "settled" and m.signed_settlement:
        return dict(m.signed_settlement)
    if m.status == "void":
        return {
            "status": "void",
            "reason": (
                "Match was voided — each stake refunds on-chain via "
                "refundTimeoutMatch after the 30-minute escrow timeout."
            ),
        }
    try:
        result = eng.settle(m)
    except MatchError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if result.get("status") == "settled":
        envelope = _attach_signed_envelope(m, result)
        # C5 — economy ledger: the settlement is a FACT; the ledger (Admin
        # SDK, bypassing the client-blocking security rules) is the writer the
        # firestore.rules comment anticipated. Best-effort — never blocks.
        economy.record_settlement(m)
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
    except (MatchError, HTTPException):
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
    envelope = store.update(match_id, _settle_once)
    return envelope


@app.post("/api/match/{match_id}/claim")
def claim_match(match_id: str, body: ClaimRequest, request: Request) -> dict[str, Any]:
    """C5 — on-chain claim persistence. After the winner's settleDuel tx is
    broadcast, the client posts the tx hash here; the server records it in the
    match ledger so the certificate can display REAL on-chain proof instead of
    the permanent 'LOCAL RESULT · NOT ON-CHAIN' fallback. Authenticated and
    participant-only; the tx hash is user-supplied metadata, not a trust
    boundary (the chain itself remains the source of truth)."""
    address = _auth(request)
    try:
        match = store.get(match_id)
        if address not in match.players:
            raise HTTPException(status_code=403, detail="Not a participant")
    except MatchError as e:
        raise HTTPException(status_code=404, detail=str(e))
    recorded = economy.record_claim(match_id, address, body.txHash, body.signature)
    return {"ok": recorded, "onChainProof": recorded}
