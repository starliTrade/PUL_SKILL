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

# --- 4. Durable store serialization (P2.2a) ----------------------------------
from store import _match_from_doc, _match_to_doc  # noqa: E402

m4 = store.enqueue(Account.create().address.lower(), 5.0)
opp4 = Account.create().address.lower()
store.enqueue(opp4, 5.0)
for idx in range(me.ROUNDS):
    for addr, base in ((list(m4.players)[0], 210.0), (opp4, 260.0)):
        me.commit_intent(m4, addr, idx, "0x" + hashlib.sha256(f"{addr}{idx}".encode()).hexdigest())
        me.reveal_target(m4, addr, idx)
        wait_out_target(m4, addr, idx)
        me.submit_result(m4, addr, idx, base + idx * 4)
me.settle(m4)
m4.signed_settlement = {"signature": "0x" + "77" * 65}

restored = _match_from_doc(_match_to_doc(m4))
check(
    "Durable store round-trip preserves match state",
    restored.status == m4.status
    and restored.winner == m4.winner
    and restored.signed_settlement == m4.signed_settlement
    and restored.rounds == m4.rounds
    and restored.players == m4.players,
)
check("Round-trip rounds compare equal", restored.rounds == m4.rounds)
check("Round-trip players compare equal", restored.players == m4.players)

# --- 5. INDEPENDENT Solidity-parity digest check (not circular) ---------------
# Reimplements abi.encodePacked() semantics from scratch (bytes32=32 bytes,
# address=RAW 20 bytes, uint256=32 bytes) and asserts the oracle digest equals
# a digest built WITHOUT using any oracle packing helper. This is the test that
# would have caught the padded-address bug that made every signature invalid.
def _keccak_independent(data: bytes) -> bytes:
    from Crypto.Hash import keccak as _k

    h = _k.new(digest_bits=256)
    h.update(data)
    return h.digest()


_parity_match_id = "0x" + "cd" * 32
_parity_winner = "0x" + "ab" * 20
_parity_escrow = "0x" + "ef" * 20
_parity_record = {
    "status": "settled",
    "matchId": _parity_match_id,
    "winner": _parity_winner,
    "winnerTimeMs": 234,
    "loserTimeMs": 301,
    "validatedTimes": {"a": [234], "b": [301]},
    "deadline": 1_900_000_000,
}
_parity_nonce = 123456789

packed_independent = b"".join(
    [
        bytes.fromhex(_parity_match_id[2:]),          # bytes32
        bytes.fromhex(_parity_winner[2:]),            # address = RAW 20 bytes
        (234).to_bytes(32, "big"),                    # uint256
        (301).to_bytes(32, "big"),                    # uint256
        _parity_nonce.to_bytes(32, "big"),            # uint256
        _parity_record["deadline"].to_bytes(32, "big"),  # uint256
        (137).to_bytes(32, "big"),                    # uint256 chainid
        bytes.fromhex(_parity_escrow[2:]),            # address = RAW 20 bytes
    ]
)
inner_independent = _keccak_independent(packed_independent)
digest_independent = _keccak_independent(b"\x19Ethereum Signed Message:\n32" + inner_independent)

digest_oracle = oracle.build_settlement_digest(
    {
        "matchId": _parity_record["matchId"],
        "winner": _parity_record["winner"],
        "winnerTimeMs": _parity_record["winnerTimeMs"],
        "loserTimeMs": _parity_record["loserTimeMs"],
        "deadline": _parity_record["deadline"],
    },
    _parity_nonce,
    chain_id=137,
    escrow_address=_parity_escrow,
)
check(
    "Oracle digest is byte-identical to Solidity abi.encodePacked layout",
    digest_oracle == digest_independent,
)

# And the oracle really signs: the low-s signature recovers to the oracle key
# over an INDEPENDENTLY-built digest made from the parameters the server
# RETURNS (serverNonce/deadline — exactly what the client submits on-chain).
signed_parity = oracle.sign_settlement(dict(_parity_record))
packed_returned = b"".join(
    [
        bytes.fromhex(_parity_match_id[2:]),
        bytes.fromhex(_parity_winner[2:]),
        (234).to_bytes(32, "big"),
        (301).to_bytes(32, "big"),
        signed_parity["serverNonce"].to_bytes(32, "big"),
        signed_parity["deadline"].to_bytes(32, "big"),
        (137).to_bytes(32, "big"),
        # sign_settlement() binds ESCROW_ADDRESS from the environment — the
        # production behavior. The independent digest must use the same value.
        bytes.fromhex(os.environ["ESCROW_ADDRESS"].lower().removeprefix("0x")),
    ]
)
digest_returned = _keccak_independent(
    b"\x19Ethereum Signed Message:\n32" + _keccak_independent(packed_returned)
)
if hasattr(Account, "recover_hash"):
    rec = Account.recover_hash(digest_returned, signature=signed_parity["signature"])
else:
    rec = Account._recover_hash(digest_returned, signature=signed_parity["signature"])
rec_addr = getattr(rec, "address", rec)
check(
    "Oracle signature verifies over the INDEPENDENT digest (low-s, real key)",
    str(rec_addr).lower() == signed_parity["oracleAddress"].lower(),
)

# s must be in the low half of the group order (EIP-2), or the contract rejects
sig_s = int.from_bytes(bytes.fromhex(signed_parity["signature"][2:])[32:64], "big")
check(
    "Signature is canonical low-s (EIP-2)",
    sig_s <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0,
)

# Idempotent re-enqueue: the same player polling twice must get the SAME match
# (no orphan waiting matches, no deadlock where P1 never learns the match began).
s5a = "a" * 40
store5 = me.MatchStore()
m5a = store5.enqueue(s5a, 1.0)
m5a_again = store5.enqueue(s5a, 1.0)
check(
    "Re-polling the queue returns the SAME waiting match (idempotent)",
    m5a.match_id == m5a_again.match_id,
)
m5b = store5.enqueue("b" * 40, 1.0)
m5b_again = store5.enqueue("b" * 40, 1.0)
check(
    "Joiner also gets a stable match on re-poll",
    m5b.match_id == m5b_again.match_id == m5a.match_id and m5b.status == "active",
)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
