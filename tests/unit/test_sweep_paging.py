"""Audit H-12 (2026-10-22) — the re-sign sweep must page, not re-read page one.

`status=='settled' ORDER BY settled_at LIMIT 100` with no cursor means the SAME
oldest 100 matches are scanned on every pass. A single settled match that cannot
be re-signed (past the on-chain horizon, or one whose update keeps failing) sits
in that window forever, and every later settlement — including ones whose prize
is about to become unspendable — is never looked at.

This is the F-12 prize rescue: a winner who closed their tab depends on it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import store as store_module  # noqa: E402


class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _Query:
    def __init__(self, rows, cursor=None, limit=None):
        self.rows = rows
        self.cursor = cursor
        self._limit = limit

    def where(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def limit(self, n):
        return _Query(self.rows, self.cursor, n)

    def start_after(self, snap):
        return _Query(self.rows, snap.id, self._limit)

    def stream(self):
        rows = self.rows
        if self.cursor is not None:
            ids = [r.id for r in rows]
            rows = rows[ids.index(self.cursor) + 1 :]
        return rows[: self._limit] if self._limit else rows


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def where(self, *_a, **_k):
        return _Query(self.rows)

    def document(self, _id):
        return type("D", (), {"get": lambda self: _Snap(_id, None)})()


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def collection(self, _name):
        return _Collection(self.rows)


def _doc(i: int) -> dict:
    return {
        "id": f"{i:032x}",
        "match_id": f"{i:032x}",
        "status": "settled",
        "players": {},
        "rounds": {},
        "stake": 1.0,
        "signed_settlement": {"deadline": 0, "signature": "0x" + "aa" * 65},
        "settled_at": i,
        "created_at": i,
    }


@pytest.fixture
def store(monkeypatch):
    s = store_module.FirestoreStore.__new__(store_module.FirestoreStore)
    s.local = store_module.InMemoryStore()
    s.last_sweep_error = ""
    s._sweep_cursor = None
    s.last_sweep_scanned = 0
    s.sweep_backlog_suspected = False
    return s


def _with_rows(store, n, monkeypatch):
    store.db = _Db([_Snap(f"{i:032x}", _doc(i)) for i in range(n)])


def test_a_single_pass_reads_one_page(store, monkeypatch):
    _with_rows(store, 250, monkeypatch)
    found = store.sweep_stale_settlements()
    assert store.last_sweep_scanned == store_module.SWEEP_PAGE_SIZE
    assert store.sweep_backlog_suspected is True
    assert len(found) == store_module.SWEEP_PAGE_SIZE


def test_the_next_pass_continues_after_the_cursor(store, monkeypatch):
    _with_rows(store, 250, monkeypatch)
    store.sweep_stale_settlements()
    first_page_ids = {m.match_id for m in store.sweep_stale_settlements()}
    assert f"{0:032x}" not in first_page_ids, (
        "the second pass re-read the first page — settled matches 100+ are "
        "never swept (audit H-12)"
    )


def test_the_scan_wraps_after_the_last_page(store, monkeypatch):
    _with_rows(store, 30, monkeypatch)
    store.sweep_stale_settlements()
    store.sweep_stale_settlements()
    assert store._sweep_cursor is not None
    store.sweep_stale_settlements()  # nothing left -> wrap to the first page
    assert store._sweep_cursor is not None, "the cursor was lost at the end"
    assert store.last_sweep_scanned == 30


def test_a_healthy_deployment_is_not_reported_as_a_backlog(store, monkeypatch):
    _with_rows(store, 7, monkeypatch)
    store.sweep_stale_settlements()
    assert store.sweep_backlog_suspected is False


def test_health_exposes_the_backlog_flag():
    import main as server
    from fastapi.testclient import TestClient

    body = TestClient(server.app).get("/api/health").json()
    assert "backlog" in body["sweep"]
