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


class _Ref:
    """A document reference: `add()` returns (timestamp, ref), like firestore."""

    def __init__(self, rows, doc_id):
        self.rows = rows
        self.id = doc_id

    def get(self):
        row = next((r for r in self.rows if r.get("id") == self.id), None)
        return type("Snap", (), {"exists": row is not None, "to_dict": lambda _s: dict(row or {})})()

    def update(self, changes):
        for row in self.rows:
            if row.get("id") == self.id:
                row.update(changes)
                return


class _Collection:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.fail = fail

    def add(self, data):
        if self.fail:
            raise OSError("firestore unavailable")
        doc_id = f"doc{len(self.rows) + 1}"
        self.rows.append({**data, "id": doc_id})
        return (None, _Ref(self.rows, doc_id))

    def document(self, doc_id):
        return _Ref(self.rows, doc_id)

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


def test_a_failed_write_is_counted_and_reported(monkeypatch):
    """Audit L-09 changed the CONTRACT here, deliberately.

    H-10 made a failed write visible to the operator (counter + health).
    L-09 added the player: `POST /api/dispute` used to answer `ok: true` even
    when nothing was stored, so the report the payout dispute depends on could
    not exist while the reporter believed it did. `record_dispute` now raises
    `DisputeStoreUnavailable` for the HTTP layer to turn into a 503 — and the
    failure is STILL counted, so health keeps showing the outage.
    """
    import pytest

    s = _store_with(_Db(fail=True))
    with pytest.raises(store_module.DisputeStoreUnavailable):
        s.record_dispute(MATCH, {"reason": "x"})
    assert s._dispute_write_failures == 1
    # The in-process cache still has it, so the operator on this replica is not
    # left with nothing while the writer is down.
    assert s.disputes_for(MATCH)[0]["reason"] == "x"


def test_memory_mode_still_records_the_report():
    s = store_module.DurableMatchStore(backend="memory")
    dispute_id = s.record_dispute(MATCH, {"reason": "y"})
    assert dispute_id, "the player needs an id they can come back with"
    [report] = s.disputes_for(MATCH)
    assert report["reason"] == "y"
    assert report["id"] == dispute_id
    assert report["status"] == "open", "a filed report starts open, not solved"


def test_a_report_can_be_resolved_and_read_back():
    s = store_module.DurableMatchStore(backend="memory")
    dispute_id = s.record_dispute(MATCH, {"reason": "z"})
    assert s.resolve_dispute(MATCH, dispute_id, status="resolved", note="paid", by="admin")
    [report] = s.disputes_for(MATCH)
    assert (report["status"], report["resolution"], report["resolvedBy"]) == (
        "resolved",
        "paid",
        "admin",
    )
    assert report["resolvedAt"]


def test_resolving_an_unknown_id_reports_false():
    s = store_module.DurableMatchStore(backend="memory")
    s.record_dispute(MATCH, {"reason": "z"})
    assert not s.resolve_dispute(MATCH, "not-a-dispute", status="dismissed", note="", by="admin")


def test_a_durable_resolution_is_visible_to_another_replica():
    db = _Db()
    writer = _store_with(db)
    dispute_id = writer.record_dispute(MATCH, {"reason": "wrong winner"})
    assert writer.resolve_dispute(
        MATCH, dispute_id, status="resolved", note="refund approved", by="admin"
    )

    other = _store_with(db)
    [report] = other.disputes_for(MATCH)
    assert report["status"] == "resolved"
    assert report["resolution"] == "refund approved"
