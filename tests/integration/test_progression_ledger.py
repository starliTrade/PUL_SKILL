"""M31 — progression must be computed and stored by the server.

Wins/XP/level/streak lived entirely in the client's localStorage: any player
could edit them, and the streak bonus documented in the XP engine could never
fire because `winStreak` was never passed to the calculation. The ledger now
owns the numbers, and `GET /api/player/{address}/stats` reads them back.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import main as server  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import economy  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    return server.store


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


# --- the progression arithmetic (no ledger needed) ----------------------------


def test_a_win_extends_the_streak_and_a_loss_resets_it():
    winner = "0x" + "aa" * 20
    loser = "0x" + "bb" * 20

    first = economy._progression_fields(winner, {}, winner, 1.0, [200.0])
    assert first["winStreak"] == 1
    assert first["xp"] > 0
    assert first["level"] >= 1

    second = economy._progression_fields(winner, {"winStreak": 1, "xp": first["xp"]}, winner, 1.0, [200.0])
    assert second["winStreak"] == 2
    assert second["xp"] > first["xp"]

    after_loss = economy._progression_fields(loser, {"winStreak": 4, "xp": 500.0}, winner, 1.0, [400.0])
    assert after_loss["winStreak"] == 0


def test_a_void_neither_extends_nor_breaks_a_streak():
    addr = "0x" + "cc" * 20
    out = economy._progression_fields(addr, {"winStreak": 3, "xp": 400.0}, "", 1.0, [])
    assert out["winStreak"] == 3
    assert out["xp"] == 400.0  # a void awards nothing


def test_the_streak_bonus_reaches_the_ledger():
    """The bonus was dead: `winStreak` was never passed. Now it is."""
    addr = "0x" + "dd" * 20
    first = economy._progression_fields(addr, {}, addr, 1.0, [250.0])
    second = economy._progression_fields(
        addr, {"winStreak": 1, "xp": first["xp"]}, addr, 1.0, [250.0]
    )
    # Same inputs, one more win on the streak → strictly more XP.
    assert second["xp"] - first["xp"] > first["xp"]


# --- the endpoint -------------------------------------------------------------


def test_stats_requires_a_session(client):
    r = client.get("/api/player/" + "0x" + "aa" * 20 + "/stats")
    assert r.status_code == 401


def test_stats_rejects_a_malformed_address(client):
    headers = _session(client, Account.create())
    r = client.get("/api/player/not-an-address/stats", headers=headers)
    assert r.status_code == 400


def test_stats_says_unavailable_rather_than_reporting_zeros(client):
    """A zero that means "no data" must not look like "no wins"."""
    headers = _session(client, Account.create())
    r = client.get("/api/player/" + "0x" + "aa" * 20 + "/stats", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"available": False}


# --- end to end against the real ledger ---------------------------------------

pytest_emulator = pytest.mark.emulator


def _emulator_db(monkeypatch):
    """Point the ledger at the emulator, or skip."""
    firestore = pytest.importorskip("google.cloud.firestore")
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set — run scripts/start_emulator.sh --bg")
    try:
        db = firestore.Client(project="demo-pulsar")
        db.collection("_probe").document("ping").set({"ok": True})
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.skip(f"Firestore emulator unreachable at {host}: {exc}")
    import store as store_module
    from store import FirestoreStore

    monkeypatch.setattr(store_module, "_fs_store", FirestoreStore(db), raising=False)
    return db


@pytest_emulator
def test_a_player_with_no_ledger_row_is_not_reported_as_zeros(client, monkeypatch):
    """A LIVE ledger with no row for this player must not answer "all zeros".

    The memory-mode test above cannot see this: with the ledger disabled the
    endpoint short-circuits to `available: false` for a different reason. In
    production the ledger is up, so "no row" was reported as
    `available: true, wins: 0, xp: 0` — and the client overwrote a real local
    progression with it.
    """
    _emulator_db(monkeypatch)
    headers = _session(client, Account.create())
    never_played = "0x" + "77" * 20

    r = client.get(f"/api/player/{never_played}/stats", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"available": False}, (
        "a missing ledger row was reported as authoritative zeros (audit M31)"
    )


@pytest_emulator
def test_a_settlement_writes_progression_and_the_endpoint_reads_it_back(client, monkeypatch):
    db = _emulator_db(monkeypatch)

    stamp = f"m31-{time.time_ns()}"
    winner = "0x" + format(abs(hash(stamp + "w")) % (1 << 160), "040x")
    loser = "0x" + format(abs(hash(stamp + "l")) % (1 << 160), "040x")

    class FakeMatch:
        """The subset of Match that record_settlement reads."""

        match_id = stamp
        players = {winner: {"address": winner}, loser: {"address": loser}}
        stake = 1.0
        settled_at = int(time.time())
        signed_settlement = {
            "signature": "0x" + "9" * 130,
            "validatedTimes": {winner: [200.0], loser: [320.0]},
            "forfeits": {winner: False, loser: False},
        }

    match = FakeMatch()
    match.winner = winner
    economy.record_settlement(match)

    doc = db.collection("users").document(winner).get().to_dict() or {}
    assert doc.get("winStreak") == 1, doc
    assert doc.get("xp", 0) > 0, doc
    assert doc.get("level", 0) >= 1, doc

    # The endpoint serves the same numbers the ledger holds.
    headers = _session(client, Account.create())
    r = client.get(f"/api/player/{winner}/stats", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["wins"] == 1
    assert body["xp"] == doc["xp"]
    assert body["winStreak"] == 1
