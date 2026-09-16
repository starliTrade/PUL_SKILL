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
import sys
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
RL_SETTLE_MAX = 10       # settle calls per minute per address (audit #10 #7:
                         # Firestore txn + signature minting per call)
RL_CLAIM_MAX = 10        # claim calls per minute per address (audit #10 #7:
                         # an RPC receipt fetch per call — cheap-DoS surface)
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

            def _incr(txn: Any) -> dict[str, int]:
                # Audit #10 (item 1): this used to `return int(d["count"])` while
                # the caller read `d["reset_at"]` from the OUTER scope — a
                # guaranteed NameError (d is local to _incr), swallowed by the
                # broad except below, so the Firestore limiter NEVER 429'd and
                # every deployment silently degraded to per-process limiting.
                snap = doc.get(transaction=txn)
                d = snap.to_dict() or {"count": 0, "reset_at": 0}
                if now_ms >= int(d.get("reset_at", 0)):
                    d = {"count": 1, "reset_at": now_ms + window_ms}
                else:
                    d = {"count": int(d.get("count", 0)) + 1, "reset_at": int(d["reset_at"])}
                txn.set(doc, d)
                return {"count": int(d["count"]), "reset_at": int(d["reset_at"])}

            txn = fs.db.transaction()
            win = _incr(txn)  # plain callable: Firestore retries conflicts itself
            if win["count"] > limit:
                raise _rate_limited((win["reset_at"] - now_ms) / 1000.0)
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
        30 minutes of locked stake on an unwinnable match).
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
        # (single source of truth: onchain.verify_deposit — probe-testable).
        if not onchain.verify_deposit(info, m.stake, m.players):
            m.status = "void"
            return {
                "void": True,
                "reason": (
                    "On-chain duel does not match this match (stake or "
                    "participants differ) — the match is void. Both stakes "
                    "refund via refundTimeoutMatch after the 30-minute escrow "
                    "timeout."
                ),
            }
        return None  # both stakes locked AND the duel is genuinely this match — play on
    if info.get("status") == onchain.STATUS_CREATED:
        # Audit #8 F-05: the deposit timeout counts from ACTIVATION (when the
        # joiner paired), not from queue entry — a long-queued match must not
        # be voided the moment it finally pairs.
        clock_origin = m.play_started_at()
        if time.time() - clock_origin > DEPOSIT_TIMEOUT_SECONDS:
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

# Audit #8 F-09 — production configuration is MANDATORY, not optional. When
# the deployment looks like production (PULSAR_ENV=production), missing
# ALLOWED_DOMAIN / CORS_ALLOW_ORIGINS / ESCROW_ADDRESS / ESCROW_RPC_URL must
# fail startup instead of silently running with a Host-derived SIWE domain,
# Audit #10 (item 2): the "deployment looks like production" check used to
# be PULSAR_ENV == "production" EXACTLY — one typo ("prod", "Production ",
# "main") or a staging box that simply forgot the var switched every
# safeguard off (fail-open configuration). Now ANY of these implies a
# deployment that must not run with insecure defaults:
#   - PULSAR_ENV set to anything production-like (prod/production/main/release),
#   - PULSAR_ENV unset but a deployment marker present (K_SERVICE, PORT-bound
#     hosting with RENDER/TRIGGER/etc.),
#   - a real ESCROW_ADDRESS configured (money mode — the gate must not be
#     silently absent).
# Plain local dev (no env at all) still boots without configuration.
_prodlike_values = {"prod", "production", "main", "release", "staging"}
_pulsar_env = os.environ.get("PULSAR_ENV", "").strip().lower()
_deploy_markers = ("K_SERVICE", "K_REVISION", "RENDER", "FLY_MACHINE_ID", "DYNO")
_is_deployed = any(os.environ.get(marker) for marker in _deploy_markers)
_prod_like = _pulsar_env in _prodlike_values or _is_deployed
if _prod_like:
    _missing = [
        name
        for name in (
            "ALLOWED_DOMAIN",
            "CORS_ALLOW_ORIGINS",
            "ESCROW_ADDRESS",
            "ESCROW_RPC_URL",
            "ORACLE_SIGNING_SECRET",
            "ORACLE_PRIVATE_KEY",
        )
        if not os.environ.get(name)
    ]
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

# Audit #8 F-09 — TrustedHost: when ALLOWED_DOMAIN is configured, requests
# with a foreign Host header are rejected at the middleware layer instead of
# being trusted for SIWE domain binding (host-header injection hardening).
_allowed_domain = os.environ.get("ALLOWED_DOMAIN", "")
if _allowed_domain:
    try:
        from fastapi.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[_allowed_domain, _allowed_domain.removeprefix("www.")],
        )
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


@app.post("/api/queue")
def queue(body: QueueRequest, request: Request) -> dict[str, Any]:
    address = _auth(request)
    _rl_check("queue", address, RL_QUEUE_MAX)
    if body.stake not in ALLOWED_STAKES:
        raise HTTPException(status_code=400, detail="Invalid stake")
    store.sweep_expired()
    # Audit #10 (item 5): also refresh settled matches whose signed envelope
    # expired while both clients were offline (sweep-driven F-12 re-sign).
    _resign_stale_settlements()
    # Audit #8 F-13: durable idempotency — check Firestore for a live match
    # containing this address BEFORE enqueueing, so a re-poll that lands on a
    # different replica (or a recycled process) cannot mint an orphan match
    # the client might fund twice.
    live = store.player_live_match(address)
    if live is not None and live.stake == body.stake:
        return live.public_view(for_address=address)
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
        # Audit #10 (item 5): pass the match so the signature deadline is
        # clamped to activation + contract MATCH_TIMEOUT.
        envelope = sign_settlement(result, matchish=m)
    except Exception:
        m.status, m.winner, m.settled_at, m.signed_settlement = saved
        raise
    envelope["roundWins"] = result.get("roundWins", {})
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
        if deadline and time.time() < deadline:
            return envelope  # still spendable — replay as-is
        # F-12 re-sign: result unchanged, fresh deadline + nonce.
        # Audit #10 (item 5): the re-sign is clamped to activation + contract
        # MATCH_TIMEOUT — past that horizon the duel is refundable and no
        # signature can pay (sign_settlement raises and the stale envelope
        # is returned; the refund path is the only money exit left).
        try:
            fresh = sign_settlement(
                {
                    "status": "settled",
                    "matchId": m.match_id,
                    "winner": m.winner,
                    "winnerTimeMs": int(envelope.get("winnerTimeMs", 0)),
                    "loserTimeMs": int(envelope.get("loserTimeMs", 0)),
                    "validatedTimes": envelope.get("validatedTimes", {}),
                },
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
        for mid, m in list(getattr(store.memory, "matches", {}).items()):
            if m.status != "settled" or not m.signed_settlement:
                continue
            deadline = int(m.signed_settlement.get("deadline", 0) or 0)
            if not deadline or time.time() < deadline:
                continue  # still spendable / never signed
            if time.time() >= engine.settlement_deadline(m):
                continue  # past the on-chain horizon — only refund applies
            try:
                store.update(mid, _settle_once)
            except (MatchError, HTTPException):
                pass
    except Exception:
        pass  # observability nicety — must never break matchmaking


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
    envelope = store.update(match_id, _settle_once)
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
    recorded = economy.record_claim(match_id, winner, body.txHash, body.signature)
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
    db = None
    try:
        import store as _store_mod

        db = getattr(_store_mod, "_fs_store", None)
        db = db.db if db is not None else None
    except Exception:
        db = None
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
    _auth(request)  # must hold a session; reads stay public via Firestore
    normalized = name.strip().lower()
    db = None
    try:
        import store as _store_mod

        db = getattr(_store_mod, "_fs_store", None)
        db = db.db if db is not None else None
    except Exception:
        db = None
    if db is None:
        raise HTTPException(status_code=503, detail="Username registry requires the durable store (Firestore)")
    snap = db.collection("usernames").document(normalized).get()
    if not snap.exists:
        return {"available": True, "username": normalized}
    owner = (snap.to_dict() or {}).get("address", "")
    return {"available": False, "username": normalized, "taken": True, "owner": owner.lower()}
