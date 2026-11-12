"""Audit M-04 (2026-10-22) — the podium is served by the server, not Firestore.

The client used to query the `leaderboard` collection from the browser. That
forced the collection to be world-readable (every address on the podium was
enumerable), billed one read per page load with no cache, and made the document
shape the API — which is how the client ended up reading `totalEarnedUSDT`, a
field the writer has never produced.

These tests pin the replacement: one fixed shape, a bounded row count, a short
cache, and an honest answer when the durable store is absent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import leaderboard  # noqa: E402
import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import store as store_module  # noqa: E402

A = "0x" + "aa" * 20
B = "0x" + "bb" * 20


class _Snap:
    def __init__(self, doc_id: str, data: dict) -> None:
        self.id = doc_id
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class _Query:
    def __init__(self, rows: list[_Snap]) -> None:
        self._rows = rows
        self.calls = 0

    def stream(self):
        self.calls += 1
        return iter(self._rows)


class _Collection:
    def __init__(self, query: _Query) -> None:
        self._query = query
        self.order: tuple | None = None
        self.limited: int | None = None

    def order_by(self, field: str, direction: str = "ASCENDING"):
        self.order = (field, direction)
        return self

    def limit(self, n: int):
        self.limited = n
        return self

    def stream(self):
        return self._query.stream()


class _Db:
    def __init__(self, rows: list[_Snap]) -> None:
        self.query = _Query(rows)
        self.collection_obj = _Collection(self.query)

    def collection(self, name: str):
        assert name == "leaderboard"
        return self.collection_obj


@pytest.fixture(autouse=True)
def _reset():
    leaderboard.reset()
    yield
    leaderboard.reset()


def test_the_podium_is_ordered_by_wins_and_limited(monkeypatch):
    db = _Db(
        [
            _Snap(A, {"address": A, "wins": 9, "totalMatches": 12, "earnedUSDT": 14.5,
                      "bestReactionMs": 210, "xp": 900, "level": 5}),
            _Snap(B, {"address": B, "wins": 4, "totalMatches": 5, "earnedUSDT": 3.0}),
        ]
    )
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    body = TestClient(server.app).get("/api/leaderboard?limit=2").json()

    assert db.collection_obj.order == ("wins", "DESCENDING")
    assert db.collection_obj.limited == 2
    assert [row["address"] for row in body["players"]] == [A, B]
    # A row that never recorded a reaction time reports 0, not a plausible guess.
    assert body["players"][1]["bestReactionMs"] == 0
    assert body["players"][1]["level"] == 1


def test_only_display_fields_leave_the_server(monkeypatch):
    db = _Db([_Snap(A, {"address": A, "wins": 1, "internalRating": 1500, "email": "x@y"})])
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    row = TestClient(server.app).get("/api/leaderboard").json()["players"][0]

    assert set(row) == {
        "address",
        "wins",
        "totalMatches",
        "earnedUSDT",
        "bestReactionMs",
        "xp",
        "level",
    }


def test_rows_without_an_address_are_dropped(monkeypatch):
    db = _Db([_Snap("", {"wins": 3}), _Snap("not-an-address", {"wins": 2})])
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    assert TestClient(server.app).get("/api/leaderboard").json()["players"] == []


def test_a_burst_of_requests_costs_one_query(monkeypatch):
    """The TTL cache is the reason this endpoint is cheap for a busy lobby."""
    db = _Db([_Snap(A, {"address": A, "wins": 1})])
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    client = TestClient(server.app)
    for _ in range(5):
        assert client.get("/api/leaderboard").status_code == 200
    assert db.query.calls == 1


def test_a_failed_read_is_503_not_an_empty_podium(monkeypatch):
    class _Broken:
        def collection(self, _name):
            raise RuntimeError("firestore down")

    monkeypatch.setattr(store_module, "durable_db", lambda: _Broken())
    r = TestClient(server.app).get("/api/leaderboard")
    assert r.status_code == 503
    assert "temporarily unavailable" in r.json()["detail"]


def test_without_a_durable_store_the_answer_says_why(monkeypatch):
    monkeypatch.setattr(store_module, "durable_db", lambda: None)
    body = TestClient(server.app).get("/api/leaderboard").json()
    assert body["players"] == []
    assert "durable store" in body["reason"]


def test_the_limit_is_capped_server_side(monkeypatch):
    db = _Db([])
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    TestClient(server.app).get("/api/leaderboard?limit=9999")
    assert db.collection_obj.limited == leaderboard.MAX_ROWS
