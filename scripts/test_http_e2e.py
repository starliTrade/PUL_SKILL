"""
PULSAR — HTTP-level end-to-end test (the layer the smoke test never covered).

Covers, over REAL HTTP (FastAPI TestClient):
  1. SIWE auth handshake (/api/auth/nonce → wallet signs → /api/auth/verify)
  2. Invalid stake rejected (ALLOWED_STAKES gate — the old NameError crash site)
  3. Idempotent matchmaking over HTTP (re-poll returns the SAME match; two
     players pair; no orphan matches)
  4. Full commit → reveal → submit round protocol, including the anti-cheat
     timing floor rejecting an instant submission
  5. Bo3 settlement + oracle signature that recovers to the oracle address
  6. Idempotent settlement replay (second settle call returns the same sig)

Run with the project venv: .venv/bin/python scripts/test_http_e2e.py
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

os.environ["ORACLE_SIGNING_SECRET"] = "e2e-test-secret"
os.environ["ORACLE_PRIVATE_KEY"] = "0x" + "11" * 32
os.environ["ESCROW_ADDRESS"] = "0x" + "ab" * 20

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as server  # noqa: E402
import auth as auth_module  # noqa: E402

failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


client = TestClient(server.app)

# P0-fix regression — CORS must be present. The frontend and this API deploy
# on different origins (docs/DEPLOYMENT.md); without the middleware browsers
# blocked every cross-origin JSON+Authorization request at preflight.
_mw_names = [getattr(m, "cls", type(m)).__name__ for m in server.app.user_middleware]
check("CORSMiddleware is installed", "CORSMiddleware" in _mw_names)

DOMAIN = "pulsar.test"


def make_session(account: Account, domain: str = DOMAIN) -> tuple[str, dict]:
    """Full SIWE handshake over HTTP; returns (bearer token, address).
    Audit-#4: the wallet signs the SERVER's returned message VERBATIM — the
    previous version rebuilt its own message, which masked the server-side
    chain-ID regression (server built 137, verifier demanded 80002 → every
    real client got 401)."""
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": domain})
    assert r.status_code == 200, r.text
    nonce = r.json()["nonce"]
    message = r.json()["message"]  # sign EXACTLY what the server issued
    assert nonce in message, "server message must embed the issued nonce"
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify",
        json={"message": message, "signature": sig},
        headers={"host": domain},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"], addr


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "host": DOMAIN}


# --- 1. SIWE over HTTP --------------------------------------------------------
alice = Account.create()
bob = Account.create()
token_a, addr_a = make_session(alice)
token_b, addr_b = make_session(bob)
check("SIWE handshake issues a session over HTTP", bool(token_a) and bool(token_b))
check("Verified address matches the signer", addr_a == alice.address.lower())

# Tampered signature must fail
r = client.post(
    "/api/auth/verify",
    json={"message": "x wants you to sign in with your Polygon account:\n0x" + "1" * 40, "signature": "0x" + "22" * 65},
    headers={"host": DOMAIN},
)
check("SIWE rejects tampered message (401)", r.status_code == 401)

# Unauthenticated privileged route must fail
r = client.post("/api/queue", json={"stake": 1.0})
check("Queue requires a bearer token (401)", r.status_code == 401)

# --- 2. Stake gate (the old ALLOWED_STAKES NameError crash site) ---------------
r = client.post("/api/queue", json={"stake": 999.0}, headers=auth_headers(token_a))
check("Invalid stake rejected (400, no 500)", r.status_code == 400)

# --- 3. Idempotent matchmaking over HTTP ---------------------------------------
r1 = client.post("/api/queue", json={"stake": 2.0}, headers=auth_headers(token_a))
check("Queue accepts a valid stake", r1.status_code == 200)
m1 = r1.json()
check("Creator sees waiting + youAreCreator=true", m1["status"] == "waiting" and m1["youAreCreator"] is True)

r1b = client.post("/api/queue", json={"stake": 2.0}, headers=auth_headers(token_a))
m1b = r1b.json()
check("Creator re-poll returns the SAME waiting match (idempotent over HTTP)", m1b["matchId"] == m1["matchId"])

r2 = client.post("/api/queue", json={"stake": 2.0}, headers=auth_headers(token_b))
m2 = r2.json()
check("Joiner pairs into the SAME match (active)", m2["matchId"] == m1["matchId"] and m2["status"] == "active")
check("Joiner sees youAreCreator=false", m2["youAreCreator"] is False)
check("Joiner sees the opponent address", (m2.get("opponent") or "").lower() == addr_a)

# Creator must now learn the match went active — the old deadlock.
r1c = client.post("/api/queue", json={"stake": 2.0}, headers=auth_headers(token_a))
m1c = r1c.json()
check("Creator re-poll sees the match ACTIVE (deadlock fixed)", m1c["status"] == "active")

# No orphan matches: exactly one waiting-or-active match for this stake.
live = [m for m in server.store.memory.matches.values() if m.status in ("waiting", "active") and m.stake == 2.0]
check("Exactly one live match exists (no orphans)", len(live) == 1)

# --- 4. Full round protocol over HTTP ------------------------------------------
match_id = m1["matchId"]


def play_round(token: str, idx: int, ms: float, honest_wait: bool, with_proof: bool = True) -> dict:
    addr = addr_a if token == token_a else addr_b
    intent = "0x" + hashlib.sha256(f"intent-{token[:8]}-{idx}-{ms}".encode()).hexdigest()
    r = client.post("/api/round/commit", json={"matchId": match_id, "roundIndex": idx, "intentHash": intent}, headers=auth_headers(token))
    if r.status_code != 200:
        return {"http": r.status_code, "detail": r.json().get("detail")}
    r = client.post("/api/round/target", json={"matchId": match_id, "roundIndex": idx}, headers=auth_headers(token))
    if r.status_code != 200:
        return {"http": r.status_code, "detail": r.json().get("detail")}
    result_proof = r.json().get("resultProof", "")
    if not with_proof:
        result_proof = ""  # simulate the audit cheat: submit without the proof
    if honest_wait:
        # Simulate the wall-clock wait on the server object (test clock control).
        # The claim is measured from target appearance, so the rewind models a
        # real player's reaction — the server's claim-vs-observed gate (audit
        # #4) rejects a claim faster than the observed submission timing.
        for m in server.store.memory.matches.values():
            if m.match_id == match_id:
                rr = m.rounds.get(addr, {}).get(idx)
                if rr and rr.revealed_at:
                    rr.revealed_at -= (rr.target_ms + ms) / 1000.0
    r = client.post(
        "/api/round/result",
        json={"matchId": match_id, "roundIndex": idx, "measuredMs": ms, "resultProof": result_proof},
        headers=auth_headers(token),
    )
    return r.json() if r.status_code == 200 else {"http": r.status_code, "detail": r.json().get("detail")}


# Reveal before commit must 409
r = client.post("/api/round/target", json={"matchId": match_id, "roundIndex": 0}, headers=auth_headers(token_a))
check("Reveal before commit rejected (409)", r.status_code == 409)

# Commit without a result proof must be rejected outright (audit-#2 cheat).
res = play_round(token_a, 0, 250.0, honest_wait=False, with_proof=False)
check("Result without the per-player proof is rejected", res.get("detail") is not None and "proof" in str(res.get("detail", "")))
# The proof-less attempt stored nothing (the proof gate runs before the round
# is consumed), so round 0 is recoverable — completing it WITH the real proof
# must now succeed.
res = play_round(token_a, 0, 250.0, honest_wait=True)
check("Round 0 recoverable after the rejected proof-less attempt", res.get("accepted") is True)
# Honest play on fresh rounds: instant submission is now a protocol failure.
res = play_round(token_a, 1, 240.0, honest_wait=False)
check("Instant submission without the target wait fails", res.get("detail") is not None or res.get("accepted") is False)

# Bob plays all rounds honestly & fast; Alice burned round 0 (forfeit), wins 1&2? No:
# honest plays: alice rounds 1,2 valid; bob all valid faster on r1, slower r2.
# Premature settle MUST be refused: honest play for Alice first, then settle
# before Bob has played a single round (audit #2: this settled 3-0 before).
for idx, ms in ((1, 240.0), (2, 260.0)):
    play_round(token_a, idx, ms, honest_wait=True)
r = client.post(f"/api/match/{match_id}/settle", json={}, headers=auth_headers(token_a))
check("Premature settle refused while opponent silent (409)", r.status_code == 409)

# Bob now plays honestly; the settle that COMPLETES the match succeeds and
# every future call replays the same oracle signature.
for idx, ms in ((0, 300.0), (1, 300.0), (2, 300.0)):
    res = play_round(token_b, idx, ms, honest_wait=True)
    check(f"Round {idx} accepted for Bob", res.get("accepted") is True)

# --- 5. Settlement + oracle signature over HTTP ---------------------------------
r = client.post(f"/api/match/{match_id}/settle", json={}, headers=auth_headers(token_a))
check("Settle succeeds over HTTP", r.status_code == 200, )
s = r.json()
check("Match settles with a winner", s.get("status") == "settled" and bool(s.get("winner")))
check("Settlement carries an oracle signature", str(s.get("signature", "")).startswith("0x") and len(s["signature"]) == 132)

if s.get("status") == "settled":
    import oracle as oracle_mod  # noqa: E402
    digest = oracle_mod.build_settlement_digest(
        {
            "matchId": s["matchId"],
            "winner": s["winner"],
            "winnerTimeMs": s["winnerTimeMs"],
            "loserTimeMs": s["loserTimeMs"],
            "deadline": s["deadline"],
        },
        s["serverNonce"],
        escrow_address=os.environ["ESCROW_ADDRESS"],
    )
    if hasattr(Account, "recover_hash"):
        rec = Account.recover_hash(digest, signature=s["signature"])
    else:
        rec = Account._recover_hash(digest, signature=s["signature"])
    rec_addr = getattr(rec, "address", rec)
    check("Settlement signature recovers to the oracle address", str(rec_addr).lower() == s["oracleAddress"].lower())
    check("Round-win accounting is included (Bo3)", bool(s.get("roundWins")) and bool(s.get("validatedTimes")))

# --- 6. Idempotent settlement replay --------------------------------------------
r2s = client.post(f"/api/match/{match_id}/settle", json={}, headers=auth_headers(token_b))
check("Second settle call replays the SAME signature (idempotent)", r2s.status_code == 200 and r2s.json().get("signature") == s["signature"])

# P0-fix regression — the match view must answer BOTH verbs. The client's
# in-game refresh previously 405'd here (POST-only helper vs GET-only route)
# and the whole round flow died at the first getMatch().
r_get = client.get(f"/api/match/{match_id}", headers=auth_headers(token_a))
r_post = client.post(f"/api/match/{match_id}", json={}, headers=auth_headers(token_a))
check("Match view answers GET (200)", r_get.status_code == 200)
check("Match view answers POST identically (client compat, no 405)", r_post.status_code == 200 and r_post.json()["matchId"] == r_get.json()["matchId"])

# Outsiders cannot settle a match they are not part of.
carol = Account.create()
token_c, _ = make_session(carol)
r = client.post(f"/api/match/{match_id}/settle", json={}, headers=auth_headers(token_c))
check("Outsider settle rejected (403)", r.status_code == 403)

# --- 7. Audit-#4 SIWE & anti-cheat regressions ---------------------------------

# 7a. The server's own SIWE message verifies (the audit's exact repro was 401
# because main.py built its statement with Chain ID 137 while auth.py
# verified 80002).
r = client.post("/api/auth/nonce", json={"address": addr_a}, headers={"host": DOMAIN})
server_msg = r.json()["message"]
sig = alice.sign_message(encode_defunct(text=server_msg)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
r = client.post("/api/auth/verify", json={"message": server_msg, "signature": sig}, headers={"host": DOMAIN})
check("Server-issued SIWE message verifies (chain regression fixed)", r.status_code == 200)

# 7b. A statement bound to a different chain is refused.
forged_chain = server_msg.replace(f"Chain ID: {auth_module.EXPECTED_CHAIN_ID}", "Chain ID: 137")
sig = alice.sign_message(encode_defunct(text=forged_chain)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
r = client.post("/api/auth/verify", json={"message": forged_chain, "signature": sig}, headers={"host": DOMAIN})
check("SIWE statement with a wrong chain ID is refused", r.status_code == 401)

# 7c. A self-forged nonce (never issued by the server) is dead on arrival.
forged_msg = server_msg.split("Nonce: ")[0] + "Nonce: deadbeef-deadbeefdeadbeef\nIssued At: 2026-01-01T00:00:00+00:00\n"
sig = alice.sign_message(encode_defunct(text=forged_msg)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
r = client.post("/api/auth/verify", json={"message": forged_msg, "signature": sig}, headers={"host": DOMAIN})
check("Self-forged nonce is refused", r.status_code == 401)

# 7c-bis. Audit-#6 C2 regression: the EXACT offline forgery — a well-formed
# payload with a CURRENT window and a GARBAGE MAC. Under the old verifier
# (which never compared the HMAC) this authenticated with 200; the MAC check
# must now kill it at the door.
_current_window = int(time.time() // auth_module.NONCE_WINDOW_SECONDS)
_forged_payload = auth_module._b64url_hex(
    f"{DOMAIN}|{addr_a}|{_current_window}|cafebabe".encode()
)
_forged_nonce = _forged_payload + "." + "0" * 64
forged_msg2 = server_msg.replace(
    server_msg.split("Nonce: ")[1].split("\n")[0], _forged_nonce
)
sig = alice.sign_message(encode_defunct(text=forged_msg2)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
r = client.post("/api/auth/verify", json={"message": forged_msg2, "signature": sig}, headers={"host": DOMAIN})
check("Well-formed nonce with a garbage MAC is refused (audit #6 C2)", r.status_code == 401)

# 7d. Tamper-evidence: the statement's chain line is altered after issuance —
# the signature is still by the right wallet, but the message is no longer
# the canonical challenge this server issued.
tampered = server_msg.replace(f"Chain ID: {auth_module.EXPECTED_CHAIN_ID}", f"Chain ID: {auth_module.EXPECTED_CHAIN_ID} ")
sig = alice.sign_message(encode_defunct(text=tampered)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
r = client.post("/api/auth/verify", json={"message": tampered, "signature": sig}, headers={"host": DOMAIN})
check("Tampered statement body is refused (challenge binding)", r.status_code == 401)

# 7e. The timing-gate regressions (claimed-time floor, pre-visible submission
# window, round expiry) run at engine level in test_game_server.py — the HTTP
# suite keeps its scope to auth/protocol/settlement.

# --- 8. Audit-#4: a signing failure must NOT wedge the match --------------------
# The memory store mutates in place, so a signing failure inside settle used to
# leave a settled-without-proof match forever (Firestore rolled back, memory
# didn't). The rollback must restore the active state, and a retry must settle.
import match_engine as eng_mod  # noqa: E402
from store import DurableMatchStore  # noqa: E402

fb2 = DurableMatchStore()
wa = Account.create().address.lower()
wb = Account.create().address.lower()
fm = fb2.enqueue(wa, 1.0)
fb2.enqueue(wb, 1.0)
for idx in range(eng_mod.ROUNDS):
    for paddr, claim in ((wa, 220.0), (wb, 300.0)):
        fb2.update(fm.match_id, lambda m, e=eng_mod, a=paddr, i=idx: e.commit_intent(m, a, i, "0x" + hashlib.sha256(f"{a}{i}".encode()).hexdigest()))
        fb2.update(fm.match_id, lambda m, e=eng_mod, a=paddr, i=idx: e.reveal_target(m, a, i))

        def _submit(m, e=eng_mod, a=paddr, i=idx, c=claim):
            rr = m.rounds[a][i]
            rr.revealed_at -= (rr.target_ms + c) / 1000.0
            return e.submit_result(m, a, i, c, rr.result_proof)

        fb2.update(fm.match_id, _submit)

orig_sign = server.sign_settlement
server.sign_settlement = lambda result: (_ for _ in ()).throw(RuntimeError("KMS unavailable"))
try:
    try:
        fb2.update(fm.match_id, server._settle_once)
        check("Sign failure surfaces instead of being swallowed", False)
    except RuntimeError:
        check("Sign failure surfaces instead of being swallowed", True)
    m_after = fb2.get(fm.match_id)
    check("Rollback on sign failure: match is NOT settled", m_after.status == "active")
    check("Rollback on sign failure: no proofless settlement stored", not m_after.signed_settlement)
finally:
    server.sign_settlement = orig_sign

out = fb2.update(fm.match_id, server._settle_once)
check(
    "Retry after a sign failure settles with a real signature",
    out.get("status") == "settled" and str(out.get("signature", "")).startswith("0x"),
)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL HTTP E2E TESTS PASSED")
