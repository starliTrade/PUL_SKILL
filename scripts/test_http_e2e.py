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

failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


client = TestClient(server.app)

DOMAIN = "pulsar.test"


def make_session(account: Account) -> tuple[str, dict]:
    """Full SIWE handshake over HTTP; returns (bearer token, address)."""
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": DOMAIN})
    assert r.status_code == 200, r.text
    nonce = r.json()["nonce"]
    message = (
        f"{DOMAIN} wants you to sign in with your Polygon account:\n"
        f"{addr}\n"
        "\n"
        "Prove you own this wallet. This signature grants no permission to move funds or spend tokens.\n"
        "\n"
        f"URI: https://{DOMAIN}\n"
        "Version: 1\n"
        "Chain ID: 137\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    )
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify",
        json={"message": message, "signature": sig},
        headers={"host": DOMAIN},
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


def play_round(token: str, idx: int, ms: float, honest_wait: bool) -> dict:
    intent = "0x" + hashlib.sha256(f"intent-{token[:8]}-{idx}-{ms}".encode()).hexdigest()
    r = client.post("/api/round/commit", json={"matchId": match_id, "roundIndex": idx, "intentHash": intent}, headers=auth_headers(token))
    if r.status_code != 200:
        return {"http": r.status_code, "detail": r.json().get("detail")}
    r = client.post("/api/round/target", json={"matchId": match_id, "roundIndex": idx}, headers=auth_headers(token))
    if r.status_code != 200:
        return {"http": r.status_code, "detail": r.json().get("detail")}
    if honest_wait:
        # Simulate the wall-clock wait on the server object (test clock control).
        for m in server.store.memory.matches.values():
            if m.match_id == match_id:
                rr = m.rounds.get(addr_a if token == token_a else addr_b, {}).get(idx)
                if rr and rr.revealed_at:
                    rr.revealed_at -= rr.target_ms / 1000.0
    r = client.post("/api/round/result", json={"matchId": match_id, "roundIndex": idx, "measuredMs": ms}, headers=auth_headers(token))
    return r.json() if r.status_code == 200 else {"http": r.status_code, "detail": r.json().get("detail")}


# Reveal before commit must 409
r = client.post("/api/round/target", json={"matchId": match_id, "roundIndex": 0}, headers=auth_headers(token_a))
check("Reveal before commit rejected (409)", r.status_code == 409)

res = play_round(token_a, 0, 250.0, honest_wait=False)
check("Anti-cheat: instant submission after reveal is REJECTED", res.get("accepted") is False)

# Burned round: resubmission must 409
r = client.post("/api/round/result", json={"matchId": match_id, "roundIndex": 0, "measuredMs": 250.0}, headers=auth_headers(token_a))
check("Rejected round cannot be re-rolled (409)", r.status_code == 409)

# Bob plays all rounds honestly & fast; Alice burned round 0 (forfeit), wins 1&2? No:
# honest plays: alice rounds 1,2 valid; bob all valid faster on r1, slower r2.
res = play_round(token_a, 1, 240.0, honest_wait=True)
check("Round 1 accepted for Alice after honest wait", res.get("accepted") is True)
res = play_round(token_a, 2, 260.0, honest_wait=True)
check("Round 2 accepted for Alice", res.get("accepted") is True)
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

# Non-participant cannot settle
carol = Account.create()
token_c, _ = make_session(carol)
r = client.post(f"/api/match/{match_id}/settle", json={}, headers=auth_headers(token_c))
check("Non-participant settle rejected (404/403)", r.status_code in (403, 404))

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL HTTP E2E TESTS PASSED")
