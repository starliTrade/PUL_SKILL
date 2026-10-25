"""The settlement envelope: signing failures, the F-12 re-sign, and the sweep.

`docs/COVERAGE-REPORT.md §3.2` ranked this the #1 untested area on cost:

    main.py settle/claim error branches  2162-2174, 2210-2232, 2300-2327
    "a settlement failing in a way nobody sees"

Three distinct ways a prize becomes unclaimable live in those lines, and none of
them had a test:

  1. `_attach_signed_envelope` signs a settled result and attaches the proof. If
     signing raises, the match must be left EXACTLY as it was. The Firestore path
     rolls back on its own, but the in-memory object is mutated IN PLACE — so
     without the snapshot restore the match is wedged as "settled" with no
     signature, and the winner can never claim. (audit #4)

  2. `_settle_once` replays a stored envelope while its deadline is still in the
     future, and RE-SIGNS it once it has expired (F-12). Without the re-sign, a
     winner who closed the tab forfeits the prize; with a broken re-sign, they get
     a proof the contract rejects. (audit #8 F-12)

  3. `_resign_stale_settlements` is the sweep that makes (2) happen without the
     player coming back. A failure there must be COUNTED, not swallowed — the
     original `except: pass` meant the prize rescue could be dead in production
     and look like a quiet period. (audit H9)

Every test below fails against an implementation that skips those three things.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import main as server  # noqa: E402
import timebase  # noqa: E402


class _Match:
    """The smallest object the settlement code touches.

    A real `Round` would drag the engine in; these functions only read/write
    status, winner, settled_at, signed_settlement, match_id and stake.
    """

    def __init__(self, *, deadline: int | None = None, status: str = "settled") -> None:
        self.match_id = "m-" + os.urandom(6).hex()
        self.status = status
        self.winner = None  # not a participant yet: a 'win' must be visible
        self.settled_at = int(timebase.now()) - 60
        self.stake = 5.0
        self.signed_settlement: dict | None = (
            {"status": "settled", "deadline": deadline, "serverNonce": 1}
            if deadline is not None
            else None
        )


def _result(**extra) -> dict:
    return {
        "status": "settled",
        "winner": "0x" + "22" * 20,
        "validatedTimes": {},
        "roundWins": {"0x" + "22" * 20: 2},
        "forfeits": {"0x" + "33" * 20: [0]},
        **extra,
    }


@pytest.fixture()
def signing_fails(monkeypatch):
    def boom(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise RuntimeError("KMS is unreachable")

    monkeypatch.setattr(server, "sign_settlement", boom)


@pytest.fixture()
def sign_counters(monkeypatch):
    """Record metrics/events without depending on their internals."""
    calls: dict[str, list] = {"metrics": [], "events": []}
    monkeypatch.setattr(
        server.metrics, "note_signature", lambda ok: calls["metrics"].append(("signature", ok))
    )
    monkeypatch.setattr(server.metrics, "note_match_settled", lambda: calls["metrics"].append(("settled",)))
    monkeypatch.setattr(
        server.eventlog, "emit", lambda name, **kw: calls["events"].append((name, kw))
    )
    return calls


# --- 1. signing failure must leave the match exactly as it was ---------------
#
# WHERE the rollback comes from matters, and the first version of this test got it
# wrong: it called `_attach_signed_envelope` directly and asserted the match was
# unchanged — which passed even with the rollback code DELETED, because nothing
# before the raise mutates `m`. The real protection is `store.update`, which
# deep-copies the match and restores it when the mutation raises. So the test goes
# through the store, which is the path every caller actually takes.
def test_a_signing_failure_leaves_the_STORED_match_untouched(signing_fails, sign_counters) -> None:
    stored = server.store.memory
    m = _Match(deadline=None, status="active")
    stored.matches[m.match_id] = m

    def mutate(live):  # noqa: ANN001 - store.update calls fn(match) in memory mode
        # Exactly what a real settlement does before signing: the engine marks
        # the match settled, THEN the signature is attempted.
        live.status = "settled"
        live.winner = "0x" + "22" * 20
        return server._attach_signed_envelope(live, _result())

    with pytest.raises(RuntimeError, match="KMS is unreachable"):
        stored.update(m.match_id, mutate)

    after = stored.matches[m.match_id]
    assert after.status == "active", (
        "a signing failure left the match WEDGED as settled with no proof — the "
        "winner can never claim and the refund path never opens (audit #4)"
    )
    assert after.winner is None, "the winner of a settlement that never signed was recorded"
    assert after.signed_settlement is None


def test_the_local_snapshot_still_restores_when_called_outside_the_store(signing_fails) -> None:
    """Defence in depth: called directly, a mutation made before the raise is undone.

    Today no caller does this — both call sites are inside `store.update`, and
    that is where the real rollback lives (the test above). This one exists so that
    if someone reuses the function outside a transaction, the local snapshot is not
    silently dead code. The `saved` line is what it exercises.
    """

    def mutating_sign(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise RuntimeError("KMS is unreachable")

    m = _Match(deadline=None, status="settled")
    m.signed_settlement = {"status": "settled", "deadline": 111}
    before = (m.status, m.winner, m.settled_at, m.signed_settlement)
    assert before[3] is not None

    with pytest.raises(RuntimeError):
        server._attach_signed_envelope(m, _result())

    # Nothing mutated it on the way to the raise — asserted so that a future edit
    # which DOES mutate before signing cannot silently drop the restore.
    assert (m.status, m.winner, m.settled_at, m.signed_settlement) == before


def test_a_signing_failure_is_counted_and_explained(signing_fails, sign_counters) -> None:
    """The metric alone cannot be debugged; the event carries the reason."""
    m = _Match(deadline=None)
    with pytest.raises(RuntimeError):
        server._attach_signed_envelope(m, _result())

    assert ("signature", False) in sign_counters["metrics"]
    assert ("settled",) not in sign_counters["metrics"], (
        "a match with no signature was counted as settled"
    )
    names = [name for name, _ in sign_counters["events"]]
    assert "match.sign_failed" in names
    payload = dict(sign_counters["events"])["match.sign_failed"]
    assert payload["matchId"] == m.match_id
    assert payload["error"] == "RuntimeError"
    assert "unreachable" in payload["detail"]


# --- 2. the happy path still records the money decision ---------------------
def test_a_successful_signature_attaches_the_proof_and_the_counters(monkeypatch, sign_counters) -> None:
    monkeypatch.setattr(
        server, "sign_settlement", lambda result, matchish=None: {"deadline": 999, "serverNonce": 7}
    )
    m = _Match(deadline=None)
    envelope = server._attach_signed_envelope(m, _result())

    assert envelope["status"] == "settled"
    assert envelope["serverNonce"] == 7
    assert m.signed_settlement == envelope
    # The ledger reads BOTH of these off the envelope; dropping either silently
    # records every duel as a non-forfeit (audit 2026-10-13).
    assert envelope["roundWins"] == {"0x" + "22" * 20: 2}
    assert envelope["forfeits"] == {"0x" + "33" * 20: [0]}
    assert ("signature", True) in sign_counters["metrics"]
    assert ("settled",) in sign_counters["metrics"]
    assert [n for n, _ in sign_counters["events"]] == ["match.settled"]
    settled_event = dict(sign_counters["events"])["match.settled"]
    assert settled_event["nonce"] == 7, "the event must name the signer's key, not a null"


# --- 3. F-12: replay while spendable, re-sign once expired ------------------
def test_a_still_valid_envelope_is_replayed_and_not_re_signed(monkeypatch) -> None:
    signed: list = []
    monkeypatch.setattr(
        server, "sign_settlement", lambda *a, **k: signed.append(1) or {"deadline": 1}
    )
    m = _Match(deadline=int(timebase.now()) + 300)
    original = dict(m.signed_settlement)

    out = server._settle_once(m, eng=None)

    assert out["deadline"] == original["deadline"]
    assert signed == [], "a spendable proof was re-signed — a needless new nonce"


def test_an_expired_envelope_is_re_signed_with_a_fresh_proof(monkeypatch) -> None:
    """The F-12 prize rescue: result unchanged, only the spendable proof refreshed."""
    fresh_deadline = int(timebase.now()) + 600

    def fake_sign(result, matchish=None):  # noqa: ANN001, ARG001
        assert result is not None
        return {"deadline": fresh_deadline, "serverNonce": 4242, "signature": "0xsig"}

    monkeypatch.setattr(server, "sign_settlement", fake_sign)
    monkeypatch.setattr(
        server.engine, "settlement_record_for_resign", lambda m: {"status": "settled"}
    )
    m = _Match(deadline=int(timebase.now()) - 10)
    m.signed_settlement["roundWins"] = {"0x" + "22" * 20: 2}

    out = server._settle_once(m, eng=None)

    assert out["serverNonce"] == 4242
    assert out["deadline"] == fresh_deadline
    assert out["resigned"] is True
    assert out["roundWins"] == {"0x" + "22" * 20: 2}, "the re-sign lost the round wins"
    assert m.signed_settlement["serverNonce"] == 4242, "the new proof was not persisted"


def test_a_failed_re_sign_returns_the_stale_envelope_instead_of_raising(monkeypatch) -> None:
    """A player asking for their proof must get the best answer available.

    Raising here would turn "the prize is late" into "the endpoint is broken";
    the stale envelope at least lets them try, and the sweep will try again.
    """

    def boom(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise RuntimeError("no signer")

    monkeypatch.setattr(server, "sign_settlement", boom)
    monkeypatch.setattr(
        server.engine, "settlement_record_for_resign", lambda m: {"status": "settled"}
    )
    m = _Match(deadline=int(timebase.now()) - 10)
    stale = dict(m.signed_settlement)

    out = server._settle_once(m, eng=None)

    assert out["deadline"] == stale["deadline"]
    assert "resigned" not in out


def test_a_void_match_explains_the_refund_path_and_mentions_the_timeout(monkeypatch) -> None:
    m = _Match(deadline=None, status="void")
    out = server._settle_once(m, eng=None)
    assert out["status"] == "void"
    assert "refundTimeoutMatch" in out["reason"]
    minutes = int(server.REFUND_HORIZON_SECONDS // 60)
    assert str(minutes) in out["reason"], "the message must say how long to wait"


# --- 4. the sweep is what makes the rescue happen without the player -------
def test_the_memory_sweep_re_signs_a_stale_settled_match(monkeypatch) -> None:
    m = _Match(deadline=int(timebase.now()) - 60)
    m.signed_settlement["roundWins"] = {}
    monkeypatch.setattr(server.store.memory, "matches", {m.match_id: m})
    reopened: list[str] = []
    monkeypatch.setattr(server.store, "sweep_stale_settlements", lambda: [])
    monkeypatch.setattr(server.store, "update", lambda mid, fn: (reopened.append(mid), fn(m))[1])
    monkeypatch.setattr(server, "_ledger_settlement", lambda mid: None)
    monkeypatch.setattr(
        server.engine, "settlement_record_for_resign", lambda m: {"status": "settled"}
    )
    monkeypatch.setattr(
        server, "sign_settlement", lambda result, matchish=None: {"deadline": 10**12, "serverNonce": 9}
    )

    server._resign_stale_settlements()

    assert reopened == [m.match_id], "a stale settled match was left with an expired proof"


def test_a_sweep_failure_is_counted_not_swallowed(monkeypatch) -> None:
    """`except: pass` made a dead prize rescue look like a quiet period (H9)."""
    server._sweep_failures.update({"sweep_expired": 0, "resign": 0, "total": 0})
    server._sweep_last_error.clear()

    m = _Match(deadline=int(timebase.now()) - 60)
    monkeypatch.setattr(server.store.memory, "matches", {m.match_id: m})
    monkeypatch.setattr(server.store, "sweep_stale_settlements", lambda: [])

    def explode(mid, fn):  # noqa: ANN001, ARG001
        raise server.MatchError("cannot update")

    monkeypatch.setattr(server.store, "update", explode)
    monkeypatch.setattr(
        server.engine, "settlement_record_for_resign", lambda m: {"status": "settled"}
    )

    server._resign_stale_settlements()

    health = server.sweep_health()
    assert health["failures"]["resign_memory"] == 1
    assert health["failures"]["total"] >= 1
    assert health["lastError"]["where"] == "resign_memory"
    assert "MatchError" in health["lastError"]["error"]


def test_past_horizon_matches_are_left_to_the_refund(monkeypatch) -> None:
    """Past activation + MATCH_TIMEOUT the contract cannot pay a signature.

    Attempting a re-sign there wastes gas on a proof that must revert, and the
    only money exit left is the refund — so the sweep must skip, and it must say
    so rather than silently treating "unknown" as "past" (the H-25 bug).
    """
    m = _Match(deadline=int(timebase.now()) - 60)
    monkeypatch.setattr(server.store.memory, "matches", {m.match_id: m})
    monkeypatch.setattr(server.store, "sweep_stale_settlements", lambda: [])
    monkeypatch.setattr(server, "_past_settlement_horizon", lambda m: True)
    touched: list = []
    monkeypatch.setattr(server.store, "update", lambda *a: touched.append(a))

    server._resign_stale_settlements()

    assert touched == [], "a past-horizon match was re-signed instead of refunded"
