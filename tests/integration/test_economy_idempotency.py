"""H3 regression — the economy ledger must be idempotent under concurrency.

Audit H3: `record_settlement` checked for an existing ledger row with a plain
`match_ref.get()` OUTSIDE any transaction, then committed a batch. Two replicas
(or the two call sites in main.py — `round_result` and `settle_match`) can both
observe "no row yet" and both commit their `FieldValue.increment` batch, so
`users.wins`, `users.totalMatches` and `leaderboard.earnedUSDT` are counted
TWICE for one duel. The docstring claimed atomic + idempotent; it was neither.

The test drives two concurrent settlements of the same match through the real
Firestore emulator and asserts the counters advanced exactly once.

Run with:  FIRESTORE_EMULATOR_HOST=127.0.0.1:8081
"""

from __future__ import annotations

import threading
import time

import pytest

pytestmark = pytest.mark.emulator

firestore = pytest.importorskip("google.cloud.firestore")

PROJECT = "demo-pulsar"


@pytest.fixture
def fs_db():
    import os

    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set — run scripts/start_emulator.sh --bg")
    try:
        client = firestore.Client(project=PROJECT)
        client.collection("_probe").document("ping").set({"ok": True})
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.skip(f"Firestore emulator unreachable at {host}: {exc}")
    return client


@pytest.fixture
def ledger(fs_db, monkeypatch):
    """Point economy._fs_db() at the emulator."""
    import store as store_module
    from store import FirestoreStore

    monkeypatch.setattr(store_module, "_fs_store", FirestoreStore(fs_db), raising=False)
    import economy

    return economy


class FakeMatch:
    """The subset of Match that record_settlement reads."""

    def __init__(self, match_id: str, winner: str, loser: str) -> None:
        self.match_id = match_id
        self.winner = winner
        self.players = {winner: {"address": winner}, loser: {"address": loser}}
        self.stake = 1.0
        self.settled_at = int(time.time())
        self.signed_settlement = {
            "signature": "0x" + "9" * 130,
            "validatedTimes": {winner: [220.0], loser: [310.0]},
            "forfeits": {winner: False, loser: False},
        }


def _fresh_ids(tag: str) -> tuple[str, str, str]:
    stamp = f"{tag}-{time.time_ns()}"
    return (
        "m" + stamp,
        "0x" + format(abs(hash(stamp + "w")) % (1 << 160), "040x"),
        "0x" + format(abs(hash(stamp + "l")) % (1 << 160), "040x"),
    )


def test_concurrent_settlements_count_once(ledger, fs_db):
    """Two simultaneous settlements of ONE duel must advance counters once.

    The two threads are released from a barrier so their read-modify-write
    windows overlap — which is exactly the production race between replicas.
    """
    match_id, winner, loser = _fresh_ids("h3")
    match = FakeMatch(match_id, winner, loser)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def settle() -> None:
        try:
            barrier.wait(timeout=10)
            ledger.record_settlement(match)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=settle) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"settlement raised: {errors}"

    user = fs_db.collection("users").document(winner).get().to_dict() or {}
    assert int(user.get("wins", 0)) == 1, (
        f"wins counted {user.get('wins')} times for one duel — the ledger "
        "idempotency gate is a read-then-write TOCTOU (audit H3)"
    )
    assert int(user.get("totalMatches", 0)) == 1

    board = fs_db.collection("leaderboard").document(winner).get().to_dict() or {}
    assert int(board.get("wins", 0)) == 1
    assert float(board.get("earnedUSDT", 0)) == pytest.approx(1.96, abs=0.01)


def test_replay_of_the_same_settlement_is_a_no_op(ledger, fs_db):
    """Sequential replay (the ordinary retry path) must also count once."""
    match_id, winner, loser = _fresh_ids("h3-seq")
    match = FakeMatch(match_id, winner, loser)

    ledger.record_settlement(match)
    ledger.record_settlement(match)
    ledger.record_settlement(match)

    user = fs_db.collection("users").document(winner).get().to_dict() or {}
    assert int(user.get("wins", 0)) == 1
    assert int(user.get("totalMatches", 0)) == 1


def test_settlement_id_helper_matches_production(ledger, fs_db):
    """H5 — the test helper must produce the SAME id the ledger actually wrote.

    `settlement_id_for` hard-coded an empty fifth component while
    `record_settlement` hashed the real validated times, so any test that used
    the helper to assert idempotency passed no matter what production did — a
    test that could not fail. This compares the helper against the id that
    actually landed in Firestore.
    """
    import economy

    match_id, winner, loser = _fresh_ids("h5")
    match = FakeMatch(match_id, winner, loser)
    ledger.record_settlement(match)

    doc = fs_db.collection("matches").document(match_id).get().to_dict() or {}
    written = doc.get("settlementId")
    assert written, "record_settlement wrote no settlementId"

    validated_times = {
        winner: [float(t) for t in match.signed_settlement["validatedTimes"][winner]],
        loser: [float(t) for t in match.signed_settlement["validatedTimes"][loser]],
    }
    expected = economy.settlement_id_for(
        match_id, winner, match.stake, match.settled_at, validated_times
    )
    assert written == expected, (
        "settlement_id_for does not reproduce the production id — a test using "
        "it to prove idempotency would pass regardless of what the ledger did "
        "(audit H5)"
    )


def test_settlement_id_is_stable_for_the_same_facts(ledger, fs_db):
    """The same settled facts must always hash to the same id."""
    import economy

    times = {"0x" + "aa" * 20: [220.0], "0x" + "bb" * 20: [310.0]}
    first = economy.settlement_id_for("m1", "0x" + "aa" * 20, 1.0, 1_700_000_000, times)
    second = economy.settlement_id_for("m1", "0x" + "aa" * 20, 1.0, 1_700_000_000, times)
    assert first == second

    # Different facts must produce a different id — otherwise the gate would
    # suppress a genuinely different settlement.
    other = economy.settlement_id_for("m1", "0x" + "aa" * 20, 1.0, 1_700_000_000, {"x": [1.0]})
    assert other != first


def test_concurrent_claims_cannot_both_win(ledger, fs_db):
    """H3 (closure review) — `record_claim` has the same read-then-write race.

    The claim-conflict guard reads the match document, compares
    `settlementTxHash`, and then writes — outside any transaction. Two
    concurrent claims with DIFFERENT tx hashes both pass the check, both return
    True, and the last write silently wins, so the documented invariant ("the
    first VERIFIED claim wins; nobody can rewrite a settled match's proof") is
    not enforced.

    This is the same class of bug as H3 in `record_settlement`, found by
    reviewing the phase-2 diff against the audit rather than by the audit
    itself.
    """
    match_id, winner, loser = _fresh_ids("claim")
    fs_db.collection("matches").document(match_id).set(
        {"id": match_id, "status": "settled", "winner": winner}
    )

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def claim(tx_hash: str) -> None:
        try:
            barrier.wait(timeout=10)
            results.append(ledger.record_claim(match_id, winner, tx_hash, "0xsig"))
        except BaseException as exc:  # pragma: no cover - surfaced below
            results.append(False)
            print("claim raised:", exc)

    threads = [
        threading.Thread(target=claim, args=("0x" + "aa" * 32,)),
        threading.Thread(target=claim, args=("0x" + "bb" * 32,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results.count(True) == 1, (
        f"both concurrent claims were accepted ({results}) — the first-claim-wins "
        "guard is a read-then-write TOCTOU"
    )

    recorded = (fs_db.collection("matches").document(match_id).get().to_dict() or {}).get(
        "settlementTxHash"
    )
    assert recorded in ("0x" + "aa" * 32, "0x" + "bb" * 32), (
        f"the recorded proof is not one of the submitted hashes: {recorded!r}"
    )
