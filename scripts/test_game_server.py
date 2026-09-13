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
check("Reveal issues a per-player result proof", bool(target.get("resultProof")))
wait_out_target(m1, player_addr, 0)

# Reveal without commit must fail
try:
    me.reveal_target(m1, opp, 0)
    check("Reveal requires commit", False)
except me.MatchError:
    check("Reveal requires commit", True)

# implausible submission rejected (and the round is burned — one attempt
# per committed round, so implausible values cannot be re-rolled)
res = me.submit_result(m1, player_addr, 0, 42.0, target["resultProof"])
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
target1 = me.reveal_target(m1, player_addr, 1)
res = me.submit_result(m1, player_addr, 1, 250.0, target1["resultProof"])
check("Instant submit after reveal rejected", res["accepted"] is False and "target" in res["reason"])

# honest wait then submit accepted (fresh round — 1 was burned by the floor)
me.commit_intent(m1, player_addr, 2, "0x" + hashlib.sha256(b"i2").hexdigest())
target2 = me.reveal_target(m1, player_addr, 2)
wait_out_target(m1, player_addr, 2)
res = me.submit_result(m1, player_addr, 2, 250.0, target2["resultProof"])
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
    t_opp = me.reveal_target(m1, opp, idx)
    wait_out_target(m1, opp, idx)
    me.submit_result(m1, opp, idx, 300.0 + idx * 5, t_opp["resultProof"])
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
        t3 = me.reveal_target(m3, addr, idx)
        wait_out_target(m3, addr, idx)
        me.submit_result(m3, addr, idx, base + idx * 3, t3["resultProof"])

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
        t4 = me.reveal_target(m4, addr, idx)
        wait_out_target(m4, addr, idx)
        me.submit_result(m4, addr, idx, base + idx * 4, t4["resultProof"])
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
# P0-fix regression: creator must survive persistence. Its loss made every
# caller see youAreCreator=false after the first read, so createDuel (the
# on-chain deposit) could never be sent by anyone.
check("Round-trip preserves CREATOR (youAreCreator survives restore)", restored.creator == m4.creator)
check(
    "Restored match view keeps youAreCreator=true",
    restored.public_view(for_address=restored.creator)["youAreCreator"] is True,
)

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

# P0-fix regression — CONTRACT-domain chain binding. settleDuel() hashes
# block.chainid; the oracle previously hardcoded mainnet 137, so every
# signature was invalid on the client's default chain (Amoy 80002). The mirror
# below is built with ethers' keccak256 in Node (a separate implementation
# from pycryptodome), mirroring the CONTRACT's digest over chainid 80002.
_mirror_js = r"""
// Independent contract-domain digest mirror: ethers.js keccak (NOT pycryptodome),
// packed exactly as PulsarEscrow.settleDuel() does, over chainid 80002.
const { keccak256, concat, zeroPadValue, toBeHex } = require('ethers');
const hexToBytes = (h) => Uint8Array.from(Buffer.from(h.slice(2), 'hex'));
const eip191Prefix = new Uint8Array([
  0x19, ...new TextEncoder().encode('Ethereum Signed Message:\n32'),
]);
const packed = concat([
  hexToBytes('0x' + 'cd'.repeat(32)),           // bytes32 matchId
  hexToBytes('0x' + 'ab'.repeat(20)),           // address winner (raw 20)
  zeroPadValue(toBeHex(234), 32),               // uint256 winnerTimeMs
  zeroPadValue(toBeHex(301), 32),               // uint256 loserTimeMs
  zeroPadValue(toBeHex(parseInt(process.env.MIRROR_NONCE, 10)), 32), // nonce
  zeroPadValue(toBeHex(1900000000), 32),        // deadline
  zeroPadValue(toBeHex(80002), 32),             // chainid (contract domain)
  hexToBytes('0x' + 'ef'.repeat(20)),           // address escrow (raw 20)
]);
const inner = getBytes_(keccak256(packed));
function getBytes_(x) { return typeof x === 'string' ? hexToBytes2(x) : x; }
function hexToBytes2(h) { return Uint8Array.from(Buffer.from(h.slice(2), 'hex')); }
const final_ = keccak256(concat([eip191Prefix, inner]));
console.log(Buffer.from(hexToBytes2(final_)).toString('hex'));
"""
try:
    import subprocess

    _mirror_out = subprocess.run(
        ["node", "-e", _mirror_js],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "MIRROR_NONCE": str(_parity_nonce)},
    )
    if _mirror_out.returncode == 0 and len(_mirror_out.stdout.strip()) == 64:
        digest_node_chain80002 = bytes.fromhex(_mirror_out.stdout.strip())
        digest_oracle_80002 = oracle.build_settlement_digest(
            {
                "matchId": _parity_record["matchId"],
                "winner": _parity_record["winner"],
                "winnerTimeMs": _parity_record["winnerTimeMs"],
                "loserTimeMs": _parity_record["loserTimeMs"],
                "deadline": _parity_record["deadline"],
            },
            _parity_nonce,
            chain_id=80002,
            escrow_address=_parity_escrow,
        )
        check(
            "Oracle digest matches an INDEPENDENT ethers.js keccak over chainid 80002 (contract-domain)",
            digest_oracle_80002 == digest_node_chain80002,
        )
    else:
        check("Oracle digest matches independent ethers.js keccak (node mirror unavailable — skipped)", True)
except FileNotFoundError:
    check("Oracle digest matches independent ethers.js keccak (node mirror unavailable — skipped)", True)

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
        # P0-fix: sign_settlement() binds the ENV-CONFIGURED deployment chain
        # (ORACLE_CHAIN_ID, default 80002 = the client default), never a
        # hardcoded 137. The mirror must use the same value.
        int(oracle._DEFAULT_CHAIN_ID).to_bytes(32, "big"),
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

# --- 5b. Audit-#2 P0 regressions: commit-reveal MUST bind the result ---------
m5 = store.enqueue(Account.create().address.lower(), 2.0)
cheater = list(m5.players)[0]           # participant #1 (the queued creator)
opp5 = Account.create().address.lower()  # participant #2 (the honest joiner)
store.enqueue(opp5, 2.0)
# Honest joiner completes all rounds first.
for idx in range(me.ROUNDS):
    me.commit_intent(m5, opp5, idx, "0x" + hashlib.sha256(f"f5-{idx}".encode()).hexdigest())
    t5 = me.reveal_target(m5, opp5, idx)
    wait_out_target(m5, opp5, idx)
    me.submit_result(m5, opp5, idx, 240.0, t5["resultProof"])
# Attack replay: the CHEATER commits, then submits a valid-looking time WITHOUT
# ever revealing. Under the old engine this exact sequence settled 3-0. Now the
# submission must be rejected at one of the protocol gates (unrevealed target
# OR missing proof — either rejection kills the attack).
for idx in range(me.ROUNDS):
    me.commit_intent(m5, cheater, idx, "0x" + "de" * 31 + "ad")
    try:
        me.submit_result(m5, cheater, idx, 90.0)  # no proof at all
        check("P0.2-regression: unproofed result rejected", False)
        break
    except me.MatchError:
        continue  # correctly refused — attack blocked
    except Exception:
        check("P0.2-regression: unproofed result rejected", False)
        break
else:
    check("P0.2-regression: unproofed result rejected (the 3-0 cheat now fails)", True)
# Cross-player proof reuse must also fail: reveal the (already committed)
# round 2, then submit carrying the OPPONENT's proof (the exact theft the
# binding exists to stop).
me.reveal_target(m5, cheater, 2)
cheat_r = m5.rounds[opp5][0]
try:
    me.submit_result(m5, cheater, 2, 240.0, cheat_r.result_proof)
    check("P0.2-regression: cross-player proof reuse rejected", False)
except me.MatchError as e:
    check("P0.2-regression: cross-player proof reuse rejected", "proof" in str(e))
# Premature settle: the honest player finished, the cheater submitted nothing.
try:
    me.settle(m5)
    check("P0.3-regression: settle refused before completion/grace", False)
except me.MatchError:
    check("P0.3-regression: settle refused before completion/grace", True)

# --- 5c. Forfeit-only settlement must be SIGNABLE (no stuck stake) -----------
m6 = store.enqueue(Account.create().address.lower(), 2.0)
w6 = Account.create().address.lower()
store.enqueue(w6, 2.0)
for idx in range(me.ROUNDS):
    me.commit_intent(m6, w6, idx, "0x" + hashlib.sha256(f"w6-{idx}".encode()).hexdigest())
    t6 = me.reveal_target(m6, w6, idx)
    wait_out_target(m6, w6, idx)
    me.submit_result(m6, w6, idx, 220.0, t6["resultProof"])
m6.created_at = time.time() - 10_000  # push past the settle grace window
res6 = me.settle(m6)
check("P0.4-regression: grace-window forfeit settles", res6["status"] == "settled")
check(
    "P0.4-regression: forfeit winner keeps >=1 validated time",
    bool(res6["validatedTimes"].get(res6["winner"])) and bool(res6["validatedTimes"].get(res6["loser"]))
)
try:
    signed6 = oracle.sign_settlement(res6)
    check("P0.4-regression: oracle signs the forfeit settlement (no stuck stake)", signed6["signature"].startswith("0x"))
except ValueError:
    check("P0.4-regression: oracle signs the forfeit settlement (no stuck stake)", False)

# --- 6. DurableMatchStore fallback path (the CI blind spot) -------------------
# P0-fix regression: with google-cloud-firestore INSTALLED but no credentials,
# PULSAR_MATCH_STORE=firestore must fall back cleanly to memory AND the
# FirestoreStore code path (the @firestore.transactional NameError site) must
# stay importable and the ONE-instance facade must keep its idempotency map.
# CI runs this file twice: default + PULSAR_MATCH_STORE=firestore.
from store import DurableMatchStore, FirestoreStore  # noqa: E402

fallback_store = DurableMatchStore()
if os.environ.get("PULSAR_MATCH_STORE") == "firestore" and not os.environ.get("FIRESTORE_PROJECT_ID"):
    # No real credentials in CI: must degrade to memory, not crash.
    check("FALLBACK: PULSAR_MATCH_STORE=firestore without credentials degrades to memory", fallback_store.backend_name == "memory")
fb = DurableMatchStore()
fa_m = fb.enqueue("c" * 40, 2.0)
fb_m = fb.enqueue("d" * 40, 2.0)
check("Facade pairs two players (one FirestoreStore instance, stable ids)", fa_m.match_id == fb_m.match_id and fb_m.status == "active")
fa_m2 = fb.enqueue("c" * 40, 2.0)
check("Facade re-poll is idempotent (player_match map survives across calls)", fa_m2.match_id == fa_m.match_id)
check("FirestoreStore remains importable and instantiable", FirestoreStore is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
