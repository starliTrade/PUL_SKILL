"""Audit H-10 (2026-10-22) — a dispute report must outlive the process.

`DurableMatchStore.record_dispute` appended to a plain dict on the instance. A
restart deleted every report, and a second replica never had them, so the one
artefact needed in a payout disagreement could be missing exactly when it
matters. Reports now go to `pulsar_disputes`; a failed write is counted and
surfaced on /api/health instead of being lost quietly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import store as store_module  # noqa: E402

MATCH = "a" * 32


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def where(self, field, op, value):
        assert (field, op) == ("matchId", "==")
        return _Query([r for r in self.rows if r.get("matchId") == value])

    def stream(self):
        return [_Snap(r) for r in self.rows]


class _Collection:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.fail = fail

    def add(self, data):
        if self.fail:
            raise OSError("firestore unavailable")
        self.rows.append(dict(data))

    def where(self, field, op, value):
        return _Query(self.rows).where(field, op, value)


class _Db:
    def __init__(self, fail=False):
        self.rows: list[dict] = []
        self.fail = fail

    def collection(self, name):
        assert name == "pulsar_disputes"
        return _Collection(self.rows, self.fail)


def _store_with(db):
    s = store_module.DurableMatchStore(backend="memory")
    s._fs_store = type("FS", (), {"db": db})()
    return s


def test_a_report_is_written_to_firestore():
    db = _Db()
    s = _store_with(db)
    s.record_dispute(MATCH, {"reason": "no payout", "address": "0x" + "11" * 20})

    assert db.rows and db.rows[0]["matchId"] == MATCH
    assert db.rows[0]["reason"] == "no payout"
    assert "at" in db.rows[0], "a dispute with no timestamp cannot be sequenced"


def test_reports_can_be_read_back_from_another_replica():
    db = _Db()
    _store_with(db).record_dispute(MATCH, {"reason": "wrong winner"})
    other = _store_with(db)  # a fresh instance == a different replica

    reports = other.disputes_for(MATCH)
    assert [r["reason"] for r in reports] == ["wrong winner"]


def test_a_failed_write_is_counted_not_swallowed(monkeypatch):
    s = _store_with(_Db(fail=True))
    s.record_dispute(MATCH, {"reason": "x"})
    assert s._dispute_write_failures == 1
    # The in-process cache still has it, so the operator is not left with nothing.
    assert s.disputes_for(MATCH)[0]["reason"] == "x"


def test_memory_mode_still_records_the_report():
    s = store_module.DurableMatchStore(backend="memory")
    s.record_dispute(MATCH, {"reason": "y"})
    assert s.disputes_for(MATCH) == [{"reason": "y"}]
