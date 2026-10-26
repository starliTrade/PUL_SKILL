"""Audit M-03 (2026-10-22) — a ban must not lift when the database is down.

`abuse._load` fell through to the in-process map on a store error. An address
that is not in that map resolves to "not banned", so a Firestore blip unbanned
every player whose record lived on another replica or an earlier process. The
same bug existed in `api/limits.py` and was fixed under H-02 with a
`StoreUnavailable` that the HTTP layer maps to a refusal; this is the same fix
for bans and velocity.

Second defect, found while writing this: the velocity counter moved BEFORE the
store call, so a duel that never started (over-latency ping, store contention)
still consumed one of the 20 starts and could lock an honest player out for 15
minutes.
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

import abuse  # noqa: E402
import main as server  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADDR = "0x" + "11" * 20


class _BrokenCollection:
    def document(self, _id):
        return self

    def get(self):
        raise RuntimeError("firestore unavailable")

    def set(self, _data):
        raise RuntimeError("firestore unavailable")


class _BrokenClient:
    def collection(self, _name):
        return _BrokenCollection()


@pytest.fixture
def broken_store(monkeypatch):
    """A configured client that cannot answer — the outage case, not dev mode."""
    monkeypatch.setattr(abuse, "_CLIENT", _BrokenClient())
    monkeypatch.setattr(abuse, "_CLIENT_RESOLVED", True)
    abuse._memory.clear()
    yield
    abuse._memory.clear()


def test_an_unreadable_ban_state_is_not_a_lift(broken_store):
    with pytest.raises(abuse.StoreUnavailable):
        abuse.require(ADDR)


def test_the_outage_error_is_still_an_abuse_error_for_old_callers():
    """An existing caller that only catches AbuseError must still refuse."""
    assert issubclass(abuse.StoreUnavailable, abuse.AbuseError)


def test_a_failed_ban_write_is_reported_not_swallowed(broken_store):
    with pytest.raises(abuse.StoreUnavailable):
        abuse.ban(ADDR, 3600, "collusion")


def test_memory_mode_still_works(monkeypatch):
    monkeypatch.setattr(abuse, "_CLIENT", None)
    monkeypatch.setattr(abuse, "_CLIENT_RESOLVED", True)
    abuse._memory.clear()
    abuse.ban(ADDR, 60, "test")
    with pytest.raises(abuse.AbuseError):
        abuse.require(ADDR)
    abuse.unban(ADDR)
    abuse.require(ADDR)  # no raise


def _session(client: TestClient, account: Account) -> dict[str, str]:
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": "pulsar.test"})
    message = r.json()["message"]
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify",
        json={"message": message, "signature": sig},
        headers={"host": "pulsar.test"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_queue_answers_503_not_403_when_the_status_cannot_be_read(monkeypatch, broken_store):
    """The distinction matters: 403 says "you are banned", 503 says "retry"."""
    monkeypatch.setattr(server.store, "_fs_store", None)
    server.store.memory.matches.clear()
    server.store.memory.queue.clear()
    server.store.memory.player_match.clear()

    client = TestClient(server.app)
    headers = _session(client, Account.create())
    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers)

    assert r.status_code == 503, r.text
    assert r.headers.get("retry-after") == "5"
    assert "could not be checked" in r.json()["detail"]


def test_a_duel_that_never_started_does_not_consume_a_start(monkeypatch):
    """The velocity window counts duels that OPENED, not attempts that failed."""
    monkeypatch.setattr(server.store, "_fs_store", None)
    server.store.memory.matches.clear()
    server.store.memory.queue.clear()
    server.store.memory.player_match.clear()

    client = TestClient(server.app)
    account = Account.create()
    headers = _session(client, account)

    calls: list[str] = []
    monkeypatch.setattr(abuse, "note_start", lambda addr: calls.append(addr))

    # rttMs above MAX_QUEUE_RTT: the store refuses, so no duel was created.
    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 5000}, headers=headers)
    assert r.status_code == 409, r.text
    assert calls == [], "a refused queue call counted as a duel start (audit M-03)"

    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers)
    assert r.status_code == 200, r.text
    assert calls == [account.address.lower()], "a real duel must still be counted"
