"""Audit H-18 (2026-10-22) — the username claim must be ONE transaction.

`DocumentReference.create()` is not a transactional write: it builds its own
batch and commits immediately. So the registry row could land while the profile
update (`users/{addr}.playerId`) rolled back — the name was squatted with no
owner — and the "already taken" check was not serialised with the insert, so two
concurrent claims could both pass it.

The test replaces the database with a fake that FAILS loudly if any write
bypasses the transaction, which is exactly the regression that must not return.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import store as store_module  # noqa: E402

ADDR = "0x" + "11" * 20


class _Snap:
    def __init__(self, data: dict | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict | None:
        return dict(self._data) if self._data else None


class _Doc:
    """A document that refuses every write made OUTSIDE a transaction."""

    def __init__(self, name: str, data: dict | None, tx) -> None:
        self.name = name
        self.data = data
        self.tx = tx
        self.committed = False

    def get(self, transaction=None) -> _Snap:
        if transaction is not None:
            transaction.reads.append(self.name)
        return _Snap(self.data)

    def create(self, data: dict) -> None:
        raise AssertionError(
            f"{self.name}: create() was called on the document, not on the "
            "transaction — this write is not atomic with the rest of the claim"
        )

    def set(self, data: dict, merge: bool = False) -> None:
        raise AssertionError(
            f"{self.name}: set() was called on the document, not on the "
            "transaction — this write is not atomic with the rest of the claim"
        )


class _Tx:
    def __init__(self, db) -> None:
        self.db = db
        self.reads: list[str] = []
        self.writes: list[tuple[str, str, dict]] = []

    def create(self, ref: _Doc, data: dict) -> None:
        self.writes.append(("create", ref.name, data))

    def set(self, ref: _Doc, data: dict, merge: bool = False) -> None:
        self.writes.append(("set", ref.name, data))

    def delete(self, ref: _Doc) -> None:
        self.writes.append(("delete", ref.name, {}))


class _Collection:
    def __init__(self, db, name: str) -> None:
        self.db = db
        self.name = name

    def document(self, doc_id: str) -> _Doc:
        return _Doc(f"{self.name}/{doc_id}", self.db.rows.get(f"{self.name}/{doc_id}"), self.db.tx)


class _Db:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows
        self.tx: _Tx | None = None

    def collection(self, name: str) -> _Collection:
        return _Collection(self, name)

    def transaction(self) -> _Tx:
        self.tx = _Tx(self)
        return self.tx


@pytest.fixture
def fake_db(monkeypatch):
    db = _Db({})
    monkeypatch.setattr(store_module, "durable_db", lambda: db)
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_rl_check", lambda *a, **k: None)

    # The production decorator drives the transaction; here it just runs the body.
    def _transactional(fn):
        def wrapper(transaction):
            return fn(transaction)

        return wrapper

    import google.cloud.firestore_v1.transaction as txmod

    monkeypatch.setattr(txmod, "transactional", _transactional)
    return db


def test_both_writes_go_through_the_transaction(fake_db):
    r = TestClient(server.app).post("/api/username/claim", json={"username": "Nova"})
    assert r.status_code == 200, r.text

    tx = fake_db.tx
    assert tx is not None, "the claim never opened a transaction"
    kinds = {(kind, name) for kind, name, _ in tx.writes}
    assert ("create", "usernames/nova") in kinds
    assert ("set", f"users/{ADDR}") in kinds


def test_an_existing_name_is_still_rejected(fake_db):
    fake_db.rows["usernames/nova"] = {"address": "0x" + "99" * 20, "tag": "Nova"}
    r = TestClient(server.app).post("/api/username/claim", json={"username": "Nova"})
    assert r.status_code == 409, r.text
    assert not (fake_db.tx and fake_db.tx.writes), "a refused claim still wrote"


def test_the_decorator_exists_in_the_pinned_library():
    """Audit C-04: `base_transaction` has no `transactional` in 2.20.0.

    The endpoint imported it from there, the ImportError was swallowed by a broad
    `except`, and EVERY claim was reported to the player as 409 "already taken".
    A future pin bump must keep this import path working.
    """
    from google.cloud.firestore_v1.transaction import transactional

    assert callable(transactional)
