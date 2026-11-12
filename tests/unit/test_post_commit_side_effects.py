"""What happens AFTER the settlement transaction commits — the two paths that must never lie.

`api/main.py` has two side effects that deliberately run outside the match
transaction (audit H4 and C-02a: a failure there must not roll back money):

* `_ledger_settlement` writes the economy ledger row;
* `_integrity_observe` feeds the server's own reaction-time measurement to the
  anti-cheat scorer.

Both were only exercised on the happy path — coverage showed the failure
branches (the ledger write that raises, the store read that fails, the round
with no server measurement) as never executed. That is the wrong place to have
no test, because the whole point of moving them out of the transaction is what
happens when they fail:

* a ledger row that failed to write must be VISIBLE (an event naming the match),
  not swallowed — a dispute needs the row and the signature, and they can fail
  independently;
* an integrity-scoring failure must be SWALLOWED completely — a scoring problem
  must never fail a round a player has already won, and must never score the
  CLIENT's claimed time (`measuredMs`) when the server's own `observed_ms` is
  what the anti-cheat model is built on.

The last test is the one that matters most: it asserts the value handed to
`integrity.observe` comes from the committed match, not from the request.
"""

from __future__ import annotations

from types import SimpleNamespace

import main as server
import pytest

from match_engine import MatchError


@pytest.fixture()
def emitted(monkeypatch):
    """Capture `eventlog.emit` calls instead of parsing stdout."""
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        server.eventlog, "emit", lambda name, **fields: events.append((name, fields))
    )
    return events


@pytest.fixture()
def ledger(monkeypatch):
    calls: list[object] = []

    def record(match):  # noqa: ANN001
        calls.append(match)

    monkeypatch.setattr(server.economy, "record_settlement", record)
    return calls


def _match(status="settled", rounds=None):  # noqa: ANN001
    return SimpleNamespace(matchId="m-1", status=status, rounds=rounds or {})


# --- the ledger row ----------------------------------------------------------
def test_a_settled_match_writes_the_ledger_row_once(monkeypatch, emitted, ledger):
    match = _match()
    monkeypatch.setattr(server.store, "get", lambda mid: match)

    server._ledger_settlement("m-1")

    assert ledger == [match], "the row must record the COMMITTED object, not a pre-commit copy"
    assert [name for name, _ in emitted] == ["ledger.written"]
    assert emitted[0][1] == {"matchId": "m-1"}


def test_a_replayed_settlement_does_not_write_a_second_row(monkeypatch, emitted, ledger):
    """`record_settlement` is idempotent (settlementId gate), so this is a no-op."""
    match = _match(status="voided")
    monkeypatch.setattr(server.store, "get", lambda mid: match)

    server._ledger_settlement("m-1")

    assert ledger == [], (
        "a non-settled match produced a ledger row — the row would claim a "
        "payout that never happened"
    )
    assert emitted == []


def test_an_unknown_match_is_not_an_error(monkeypatch, emitted, ledger):
    def missing(mid):  # noqa: ANN001, ARG001
        raise MatchError("no such match")

    monkeypatch.setattr(server.store, "get", missing)
    # A deleted match must not turn a completed round into a 500 for the player.
    server._ledger_settlement("gone")
    assert ledger == [] and emitted == []


def test_a_failed_ledger_write_is_loud_and_does_not_pass_silently(monkeypatch, emitted):
    def explode(match):  # noqa: ANN001, ARG001
        raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(server.economy, "record_settlement", explode)
    monkeypatch.setattr(server.store, "get", lambda mid: _match())

    with pytest.raises(RuntimeError):
        server._ledger_settlement("m-1")

    assert [name for name, _ in emitted] == ["ledger.write_failed"]
    fields = emitted[0][1]
    assert fields["matchId"] == "m-1"
    assert fields["error"] == "RuntimeError", (
        "the event must carry the exception TYPE: `error` is what an operator "
        "greps for, and a missing row with no event is an invisible money bug"
    )


# --- the integrity observation ----------------------------------------------
@pytest.fixture()
def observe(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        server.integrity, "observe", lambda addr, values, mid: seen.append((addr, values, mid))
    )
    return seen


def test_the_integrity_score_uses_the_server_measurement(monkeypatch, observe):
    """The whole point of C-02a: score what the SERVER saw, not the claim.

    `rounds[address][index].observed_ms` is written by the round timer; the
    client-supplied `measuredMs` is never read here. If this ever changes, a
    script can report a plausible 240 ms while answering in 110 ms.
    """
    rounds = {"0xabc": {0: SimpleNamespace(observed_ms=118.0, measured_ms=240.0)}}
    monkeypatch.setattr(server.store, "get", lambda mid: _match(rounds=rounds))

    server._integrity_observe("m-1", "0xABC", 0)

    assert observe == [("0xABC", [118.0], "m-1")]


def test_a_round_with_no_server_measurement_is_skipped(monkeypatch, observe):
    rounds = {"0xabc": {0: SimpleNamespace(observed_ms=None)}}
    monkeypatch.setattr(server.store, "get", lambda mid: _match(rounds=rounds))

    server._integrity_observe("m-1", "0xabc", 0)

    assert observe == [], "a missing measurement must not be scored as 0 ms"


def test_an_unknown_round_is_skipped(monkeypatch, observe):
    monkeypatch.setattr(server.store, "get", lambda mid: _match(rounds={}))
    server._integrity_observe("m-1", "0xabc", 3)
    assert observe == []


def test_a_broken_store_read_never_fails_the_round(monkeypatch, observe, capsys):
    def broken(mid):  # noqa: ANN001, ARG001
        raise RuntimeError("store down")

    monkeypatch.setattr(server.store, "get", broken)
    server._integrity_observe("m-1", "0xabc", 0)  # must not raise

    assert observe == []
    assert "observation skipped" in capsys.readouterr().err, (
        "it is swallowed on purpose, but silently: the line on stderr is the "
        "only trace that scoring was lost"
    )
