"""Audit H-14 (2026-10-22) — a failed ledger write must be retried, not mourned.

The settlement is final on-chain before the ledger runs: the winner holds the
money. If the Firestore write then failed, wins/XP/leaderboard never advanced,
the only signal was a counter on /api/health, and NOTHING ever tried again — so
the player's statistics diverged from the chain for good.

Every failure is now queued, the existing sweep drains the queue, and the drain
is safe because the ledger's idempotency gate is keyed on the settlement facts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import economy  # noqa: E402

MATCH_ID = "a" * 32


class _Ref:
    def __init__(self, store, key):
        self.store = store
        self.key = key

    def set(self, data, merge=False):
        cur = dict(self.store.rows.get(self.key, {}))
        cur.update(data)
        self.store.rows[self.key] = cur

    def delete(self):
        self.store.rows.pop(self.key, None)

    def get(self):
        return _Snap(self.key, self.store.rows.get(self.key), self)


class _Snap:
    def __init__(self, key, data, ref=None):
        self.id = key
        self._data = data
        self.exists = data is not None
        self.reference = ref

    def to_dict(self):
        return dict(self._data) if self._data else None


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def where(self, field, op, value):
        return _Query([r for r in self.rows if r[1].get(field) == value])

    def order_by(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def stream(self):
        return [_Snap(k, v, _Ref(DB, k)) for k, v in self.rows]


class _Collection:
    def __init__(self, name):
        self.name = name

    def document(self, key):
        full = f"{self.name}/{key}"
        return _Ref(DB, full) if False else _DocRef(DB, full)

    def where(self, field, op, value):
        items = [(k, v) for k, v in DB.rows.items() if k.startswith(self.name + "/")]
        return _Query([(k, v) for k, v in items if v.get(field) == value])


class _DocRef(_Ref):
    pass


class _Db:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def collection(self, name):
        return _Collection(name)


DB = _Db()


class _Store:
    def __init__(self, match):
        self.match = match
        self.calls = 0

    def get(self, _mid):
        self.calls += 1
        if self.match is None:
            raise KeyError("gone")
        return self.match


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    global DB
    DB = _Db()
    monkeypatch.setattr(economy, "_fs_db", lambda: DB)
    monkeypatch.setattr(economy, "OUTBOX_STATE", dict(economy.OUTBOX_STATE))
    for k in ("pending", "oldestAgeSeconds", "drained", "failed", "lastDrainAt"):
        economy.OUTBOX_STATE[k] = 0
    yield


def test_a_failed_settlement_is_queued_with_its_error(monkeypatch):
    """A real failure inside the ledger body (not a mock of it)."""

    class _M:
        match_id = MATCH_ID

    # `record_settlement` must reach the transaction path to fail there; give it
    # a module whose `transactional` exists so the failure is the missing
    # players attribute, not the guard.
    monkeypatch.setattr(
        economy, "_firestore_module", lambda: type("F", (), {"transactional": lambda fn: fn})
    )

    outcome = economy.record_settlement(_M())

    assert outcome == "failed"
    row = DB.rows[f"{economy.OUTBOX}/{MATCH_ID}"]
    assert row["status"] == "pending"
    assert "AttributeError" in row["lastError"] or "error" in row["lastError"].lower()


def test_the_drain_reapplies_a_queued_settlement(monkeypatch):
    DB.rows[f"{economy.OUTBOX}/{MATCH_ID}"] = {
        "matchId": MATCH_ID, "status": "pending", "at": 0, "attempts": 0
    }
    apply = {"n": 0}

    def fake_record(match):
        apply["n"] += 1
        return "written"

    monkeypatch.setattr(economy, "record_settlement", fake_record)
    store = _Store(object())
    state = economy.drain_outbox(store)

    assert apply["n"] == 1
    assert state["drained"] == 1
    assert f"{economy.OUTBOX}/{MATCH_ID}" not in DB.rows, (
        "a successfully applied settlement must leave the queue, or it is "
        "retried forever"
    )


def test_a_match_missing_on_this_replica_is_retried_later(monkeypatch):
    DB.rows[f"{economy.OUTBOX}/{MATCH_ID}"] = {
        "matchId": MATCH_ID, "status": "pending", "at": 0
    }
    monkeypatch.setattr(economy, "record_settlement", lambda m: "written")

    state = economy.drain_outbox(_Store(None))

    assert state["failed"] == 1
    row = DB.rows[f"{economy.OUTBOX}/{MATCH_ID}"]
    assert row["attempts"] == 1
    assert row["status"] == "pending", "the retry must not be dropped"


def test_an_unsuccessful_retry_stays_queued(monkeypatch):
    DB.rows[f"{economy.OUTBOX}/{MATCH_ID}"] = {
        "matchId": MATCH_ID, "status": "pending", "at": 0
    }
    monkeypatch.setattr(economy, "record_settlement", lambda m: "failed")

    state = economy.drain_outbox(_Store(object()))

    assert state["pending"] == 1
    assert f"{economy.OUTBOX}/{MATCH_ID}" in DB.rows


def test_health_reports_the_backlog():
    economy.OUTBOX_STATE["pending"] = 3
    health = economy.ledger_health()
    assert health["outbox"]["pending"] == 3
