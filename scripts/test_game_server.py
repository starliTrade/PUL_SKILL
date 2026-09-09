"""
PULSAR P1 smoke test: exercises SIWE verify, matchmaking, commit-reveal round
protocol, settlement, and oracle signature recovery. Run once, then delete.
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

os.environ["ORACLE_SIGNING_SECRET"] = "test-secret-not-for-prod"
os.environ["ORACLE_PRIVATE_KEY"] = "0x" + "11" * 32
os.environ["ESCROW_ADDRESS"] = "0x" + "ab" * 20

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

import auth  # noqa: E402
import match_engine as me  # noqa: E402
import oracle  # noqa: E402

failures = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        failures.append(name)


# --- 1. SIWE round trip -----------------------------------------------------
player = Account.create()
player_addr = player.address.lower()
domain = "pulsar.test"

nonce = auth.issue_nonce(player_addr, domain)
message = (
    f"{domain} wants you to sign in with your Polygon account:\n"
    f"{player_addr}\n"
    "\n"
    "Prove you own this wallet. This signature grants no permission to move funds or spend tokens.\n"
    "\n"
    f"URI: https://{domain}\n"
    "Version: 1\n"
    "Chain ID: 137\n"
    f"Nonce: {nonce}\n"
    f"Issued At: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    f"Expiration Time: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 600))}\n"
)
sig = player.sign_message(encode_defunct(text=message)).signature.hex()
if not sig.startswith("0x"):
    sig = "0x" + sig
recovered = auth.verify_siwe(message, sig, domain)
check("SIWE verifies the real signer", recovered == player_addr)

bad = auth.verify_siwe(message, sig, "evil.domain")
check("SIWE rejects wrong domain", bad is None)

forged = "0x" + "22" * 65
check("SIWE rejects forged signature", auth.verify_siwe(message, forged, domain) is None)

# --- 2. Matchmaking + commit/reveal + plausibility ---------------------------
store = me.MatchStore()
m1 = store.enqueue(player_addr, 1.0)
opp = Account.create().address.lower()
m2 = store.enqueue(opp, 1.0)
check("Matchmaking pairs two players", m1.match_id == m2.match_id and m1.status == "active")


def wait_out_target(match, addr, idx):
    """Simulate wall-clock elapse of the round's target delay on the server.
    The engine reads time.time() directly, so tests rewind revealed_at by the
    full target window — identical to a client waiting honestly."""
    r = match.rounds[addr].get(idx)
    if r and r.revealed_at:
        r.revealed_at -= r.target_ms / 1000.0


# playerA round flow
intent = hashlib.sha256(b"my-intent").hexdigest()
me.commit_intent(m1, player_addr, 0, "0x" + intent)
target = me.reveal_target(m1, player_addr, 0)
check("Target revealed after commit", target["targetMs"] >= 1200)
wait_out_target(m1, player_addr, 0)

# Reveal without commit must fail
try:
    me.reveal_target(m1, opp, 0)
    check("Reveal requires commit", False)
except me.MatchError:
    check("Reveal requires commit", True)

# implausible submission rejected (and the round is burned — one attempt
# per committed round, so implausible values cannot be re-rolled)
res = me.submit_result(m1, player_addr, 0, 42.0)
check("Superhuman time rejected", res["accepted"] is False and "below human minimum" in res["reason"])

# re-submission blocked — the anti-reroll guarantee
try:
    me.submit_result(m1, player_addr, 0, 250.0)
    check("Rejected round cannot be re-rolled", False)
except me.MatchError:
    check("Rejected round cannot be re-rolled", True)

# plausible submission accepted (on a fresh round)
# instant submission after reveal must be REJECTED (timing floor)
me.commit_intent(m1, player_addr, 1, "0x" + hashlib.sha256(b"i1").hexdigest())
me.reveal_target(m1, player_addr, 1)
res = me.submit_result(m1, player_addr, 1, 250.0)
check("Instant submit after reveal rejected", res["accepted"] is False and "target" in res["reason"])

# honest wait then submit accepted (fresh round — 1 was burned by the floor)
me.commit_intent(m1, player_addr, 2, "0x" + hashlib.sha256(b"i2").hexdigest())
me.reveal_target(m1, player_addr, 2)
wait_out_target(m1, player_addr, 2)
res = me.submit_result(m1, player_addr, 2, 250.0)
check("Plausible time accepted", res["accepted"] is True)

# double submission blocked
try:
    me.submit_result(m1, player_addr, 1, 250.0)
    check("Double submit blocked", False)
except me.MatchError:
    check("Double submit blocked", True)

# complete opponent's rounds; playerA has rounds 0 (invalid) + 1 (valid)
for idx in range(me.ROUNDS):
    me.commit_intent(m1, opp, idx, "0x" + hashlib.sha256(f"o{idx}".encode()).hexdigest())
    me.reveal_target(m1, opp, idx)
    wait_out_target(m1, opp, idx)
    me.submit_result(m1, opp, idx, 300.0 + idx * 5)
# Bo3 semantics: a forfeited (invalid) round is LOST. playerA burned rounds
# 0 and 1, won only round 2 (245<310) -> opponent wins 2-1. Anti-cheat has
# real teeth: cheating costs rounds, not just a warning.
result = me.settle(m1)
check("Forfeited rounds lose the match (2-1)", result["status"] == "settled" and result["winner"] == opp)

# Mutual-disclosure rule: opponent's VALID time is visible only for rounds
# where I also submitted (r0: both submitted -> 300.0 disclosed; r1: I never
# got a valid submission after the instant-submit burn -> not disclosed).
view = m1.public_view(for_address=player_addr)
check("Opponent address disclosed", view["opponent"] == opp)
check("Mutual submission discloses opponent time", abs(view["opponentTimes"].get("0", -1) - 300.0) < 0.01)
check("Opponent round counter tracks submissions", view["opponentSubmitted"] == me.ROUNDS)

# --- 3. Clean settlement + oracle signature ----------------------------------
m3 = store.enqueue(Account.create().address.lower(), 2.0)
w_addr = Account.create().address.lower()
m3b = store.enqueue(w_addr, 2.0)
for idx in range(me.ROUNDS):
    for addr, base in ((m3.players and list(m3.players)[0], 220.0), (w_addr, 280.0)):
        me.commit_intent(m3, addr, idx, "0x" + hashlib.sha256(f"{addr}{idx}".encode()).hexdigest())
        me.reveal_target(m3, addr, idx)
        wait_out_target(m3, addr, idx)
        me.submit_result(m3, addr, idx, base + idx * 3)

result = me.settle(m3)
check("Clean match settles", result["status"] == "settled")
fastest = min(result["validatedTimes"], key=lambda a: result["validatedTimes"][a][0])
check("Winner is the faster validated player", result["winner"] == fastest)

signed = oracle.sign_settlement(result)
check("Oracle signs engine settlement", signed["signature"].startswith("0x"))

# independent recovery: recompute the EXACT contract digest and recover the signer
digest = oracle.build_settlement_digest(
    {
        "matchId": result["matchId"],
        "winner": result["winner"],
        "winnerTimeMs": signed["winnerTimeMs"],
        "loserTimeMs": signed["loserTimeMs"],
        "deadline": signed["deadline"],
    },
    signed["serverNonce"],
    escrow_address=os.environ["ESCROW_ADDRESS"],
)
if hasattr(Account, "recover_hash"):
    recovered_oracle = Account.recover_hash(digest, signature=signed["signature"])
else:
    recovered_oracle = Account._recover_hash(digest, signature=signed["signature"])
recovered_addr = getattr(recovered_oracle, "address", recovered_oracle)
check("Signature recovers to oracle address", str(recovered_addr).lower() == signed["oracleAddress"].lower())

# refuse to sign client-fabricated records
try:
    oracle.sign_settlement({"status": "settled", "winner": player_addr, "matchId": "fake", "stake": 1})
    check("Oracle refuses fabricated record without validatedTimes", False)
except Exception:
    check("Oracle refuses fabricated record without validatedTimes", True)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
