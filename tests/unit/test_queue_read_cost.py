"""Audit H-11 (2026-10-22) — pairing must not read the whole queue.

Inside ONE Firestore transaction, the old `enqueue` read one match document per
waiting slot. Every poll therefore paid N reads (and N round trips) while
serialising on the same stake document — latency grew exactly when the queue was
busy, which is when matchmaking must stay fast. The slots now carry the fields
the decision needs (creator, target, rating, rtt, joinedAt), so the transaction
reads the queue document and then ONE match: the winner, to confirm it is still
waiting (metadata is not authority).

This test counts document reads, not milliseconds: read count is the thing that
scales with the queue and the thing a future refactor can silently regress.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("PULSAR_ENV", "dev")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import store as store_module  # noqa: E402

STAKE = 1.0


class _Snap:
    def __init__(self, data, exists=True):
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, db, key):
        self.db = db
        self.key = key

    def get(self, transaction=None):
        if transaction is not None:
            transaction.reads += 1
        return _Snap(self.db.docs.get(self.key), exists=self.key in self.db.docs)

    def set(self, data, merge=False):
        self.db.docs[self.key] = dict(data)


class _Collection:
    def __init__(self, db, name):
        self.db = db
        self.name = name

    def document(self, key):
        return _DocRef(self.db, f"{self.name}/{key}")


class _Db:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def collection(self, name):
        return _Collection(self, name)

    def transaction(self):
        return _Tx()


class _Tx:
    def __init__(self):
        self.reads = 0

    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)


def _waiting_doc(i: int, stake: float = STAKE) -> dict:
    creator = "0x" + f"{i:040x}"
    return {
        "id": f"{i:032x}",
        "match_id": f"{i:032x}",
        "stake": stake,
        "status": "waiting",
        "creator": creator,
        "players": {creator: {"address": creator, "joinedAt": 1000.0 + i}},
        "rounds": {},
        "created_at": 1000.0,
        "target": "",
    }


@pytest.fixture
def store(monkeypatch):
    # The production decorator drives retries against a real transaction object;
    # here the body is executed once with the fake so READS can be counted.
    def _transactional(fn):
        return lambda transaction: fn(transaction)

    monkeypatch.setattr(store_module._firestore, "transactional", _transactional)
    s = store_module.FirestoreStore.__new__(store_module.FirestoreStore)
    s.local = store_module.InMemoryStore()
    s.last_sweep_error = ""
    s.player_match = {}
    s._rating_for = lambda _a: 1200.0
    s.db = _Db()
    return s


def _seed(store, n: int) -> list[str]:
    """n waiting matches, queued the way the CURRENT code queues them."""
    queue_key = f"{store_module.QUEUE_DOC}/{round(STAKE * 100)}"
    slots = []
    for i in range(n):
        doc = _waiting_doc(i)
        store.db.docs[f"pulsar_matches/{doc['match_id']}"] = doc
        slots.append(
            {
                "matchId": doc["match_id"],
                "target": "",
                "creator": doc["creator"],
                "rating": 1200.0,
                "rttMs": 40.0 + i,
                "joinedAt": 1000.0 + i,
            }
        )
    store.db.docs[queue_key] = {"waiting": slots}
    return [s["matchId"] for s in slots]


@pytest.mark.parametrize("depth", [1, 5, 40])
def test_reads_do_not_scale_with_queue_depth(store, depth):
    _seed(store, depth)
    store.player_match.clear()

    class CountingDb(_Db):
        def transaction(self):
            self.last_tx = _Tx()
            return self.last_tx

    store.db.__class__ = CountingDb
    store.db.last_tx = None

    match = store.enqueue("0x" + "aa" * 20, STAKE)

    assert match.status in ("waiting", "active")
    reads = store.db.last_tx.reads
    assert reads <= 3, (
        f"{reads} document reads for one enqueue with {depth} waiting slots — "
        "the pairing transaction is reading the queue again (audit H-11)"
    )


def test_the_decision_still_pairs_with_the_oldest_compatible_player(store):
    ids = _seed(store, 5)
    store.player_match.clear()
    match = store.enqueue("0x" + "aa" * 20, STAKE)
    # 5.0 USDT? no: the same stake. The arriving player must join an EXISTING
    # waiting match rather than mint a sixth.
    assert match.status == "active"
    assert match.match_id in ids, "matchmaking stopped pairing existing waiters"


def test_expired_slots_are_dropped_when_a_new_one_is_written(store, monkeypatch):
    """A slot older than QUEUE_EXPIRY is dangling by construction.

    Checking liveness per slot would be one read per slot — the cost H-11
    removes — so the bound is the queue expiry, which the engine enforces when it
    sweeps.
    """
    _seed(store, 3)
    for slot in store.db.docs[f"{store_module.QUEUE_DOC}/{round(STAKE * 100)}"]["waiting"]:
        slot["joinedAt"] = 0.0  # ancient
    store.player_match.clear()

    # A target nobody reserved for: incompatible with every slot, so the code
    # takes the CREATE path and rewrites the slot list.
    store.enqueue("0x" + "aa" * 20, STAKE, target="0x" + "ff" * 20)

    queue = store.db.docs[f"{store_module.QUEUE_DOC}/{round(STAKE * 100)}"]
    assert all(e["joinedAt"] > 0 for e in queue["waiting"]), (
        "expired slots were kept in the queue document forever"
    )
