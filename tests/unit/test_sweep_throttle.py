"""H9 regression — the lazy sweep must not run on every queue poll, and a
missing Firestore index must not be swallowed.

Audit H9: `/api/queue` is the hottest endpoint (the client polls it every
2.5s), and every poll ran `sweep_expired()` + `_resign_stale_settlements()`,
which between them issue three whole-collection scans:

    QUEUE_DOC.stream()
    .where("status", "==", "active").stream()
    .where("status", "==", "settled").order_by("settled_at").limit(100)

The third query needs a composite index `(status, settled_at)` that is declared
nowhere, and `except Exception: pass` swallowed the missing-index error — so the
durable re-sign sweep (the F-12 prize rescue) silently no-opped in production
while still paying for the query. A silent no-op is worse than a crash: it looks
like it works.

Two things are pinned here:
  1. the sweep is throttled, so N polls in a window do not cost N sweeps;
  2. a sweep failure is counted and surfaced, not swallowed.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as server  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


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
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_polls_inside_the_window_do_not_re_sweep(client, monkeypatch):
    """Several queue polls in one window must cost ONE sweep, not one each."""
    headers = _session(client, Account.create())

    calls = {"n": 0}
    real_sweep = server.store.sweep_expired

    def counted():
        calls["n"] += 1
        return real_sweep()

    monkeypatch.setattr(server.store, "sweep_expired", counted)
    server._reset_sweep_clock()

    for _ in range(5):
        r = client.post("/api/queue", json={"stake": 1.0}, headers=headers)
        assert r.status_code == 200, r.text

    assert calls["n"] == 1, (
        f"the sweep ran {calls['n']} times for 5 polls — every poll pays for "
        "three collection scans on the hottest endpoint (audit H9)"
    )


def test_sweep_runs_again_after_the_window(client, monkeypatch, clock):
    """Throttling must not disable the sweep — it only spaces it out."""
    headers = _session(client, Account.create())

    calls = {"n": 0}
    real_sweep = server.store.sweep_expired

    def counted():
        calls["n"] += 1
        return real_sweep()

    monkeypatch.setattr(server.store, "sweep_expired", counted)
    server._reset_sweep_clock()

    client.post("/api/queue", json={"stake": 1.0}, headers=headers)
    clock.advance(server.SWEEP_MIN_INTERVAL_SECONDS + 1)
    client.post("/api/queue", json={"stake": 1.0}, headers=headers)

    assert calls["n"] == 2, "the sweep stopped running after the throttle window"


def test_sweep_failures_are_counted_not_swallowed(client, monkeypatch):
    """A failing sweep must be visible — a silent no-op looks like success."""
    headers = _session(client, Account.create())

    def boom():
        raise RuntimeError("simulated missing composite index")

    monkeypatch.setattr(server.store, "sweep_expired", boom)
    server._reset_sweep_clock()
    before = server.sweep_health()["failures"]["sweep_expired"]

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers)
    assert r.status_code == 200, "a sweep failure must never break matchmaking"

    after = server.sweep_health()["failures"]["sweep_expired"]
    assert after == before + 1, (
        "the sweep failure was swallowed — the durable re-sign sweep can be "
        "dead in production and nothing says so (audit H9)"
    )


def test_health_exposes_the_sweep_state(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "sweep" in body, "/api/health must surface the sweep's health (audit H9)"
    assert "failures" in body["sweep"]
