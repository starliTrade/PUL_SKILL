"""M27 — a friend challenge must actually pair the two named players.

Audit M27: "challenge a friend" was a display label. The client passed the
friend's name to the game page and the server paired the next random player at
that stake — the named friend was never involved. The UI promised a duel with a
specific person and delivered a stranger.

This makes the reservation real: a challenge is a waiting match RESERVED for a
target address. It is not offered to anyone else, and it is satisfied when the
target queues (naming the challenger, or simply queueing — both mean "yes").
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import main as server  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


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
    assert r.status_code == 200, r.text
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


def test_a_challenge_reserves_the_match_for_its_target(client):
    alice, bob, carol = Account.create(), Account.create(), Account.create()
    ha, hb, hc = _session(client, alice), _session(client, bob), _session(client, carol)
    a_addr, b_addr = alice.address.lower(), bob.address.lower()

    # Alice challenges Bob.
    r = client.post("/api/queue", json={"stake": 1.0, "opponent": b_addr}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "waiting"
    reserved = r.json()["matchId"]

    # Carol queues openly at the same stake. The reserved match is NOT hers.
    r = client.post("/api/queue", json={"stake": 1.0}, headers=hc)
    assert r.status_code == 200, r.text
    assert r.json()["matchId"] != reserved, (
        "a random player was paired into a match reserved for someone else (audit M27)"
    )

    # Bob accepts — he names Alice, and lands in HER match.
    r = client.post("/api/queue", json={"stake": 1.0, "opponent": a_addr}, headers=hb)
    assert r.status_code == 200, r.text
    assert r.json()["matchId"] == reserved
    assert r.json()["status"] == "active"


def test_the_target_accepts_by_simply_queueing(client):
    """Bob does not need to name Alice — queueing at all is an acceptance."""
    alice, bob = Account.create(), Account.create()
    ha, hb = _session(client, alice), _session(client, bob)
    b_addr = bob.address.lower()

    r = client.post("/api/queue", json={"stake": 2.0, "opponent": b_addr}, headers=ha)
    reserved = r.json()["matchId"]
    assert r.json()["status"] == "waiting"

    r = client.post("/api/queue", json={"stake": 2.0}, headers=hb)
    assert r.json()["matchId"] == reserved
    assert r.json()["status"] == "active"


def test_open_queueing_still_pairs_two_strangers(client):
    """The reservation must not break ordinary matchmaking."""
    alice, bob = Account.create(), Account.create()
    ha, hb = _session(client, alice), _session(client, bob)

    r = client.post("/api/queue", json={"stake": 5.0}, headers=ha)
    match_id = r.json()["matchId"]
    assert r.json()["status"] == "waiting"

    r = client.post("/api/queue", json={"stake": 5.0}, headers=hb)
    assert r.json()["matchId"] == match_id
    assert r.json()["status"] == "active"


def test_a_challenge_to_a_different_stake_does_not_pair(client):
    """A reservation is stake-specific: the escrow stakes must match."""
    alice, bob = Account.create(), Account.create()
    ha, hb = _session(client, alice), _session(client, bob)
    b_addr = bob.address.lower()

    r = client.post("/api/queue", json={"stake": 1.0, "opponent": b_addr}, headers=ha)
    reserved = r.json()["matchId"]

    r = client.post("/api/queue", json={"stake": 10.0}, headers=hb)
    assert r.json()["matchId"] != reserved


def test_naming_the_challenger_is_not_enough_when_they_reserved_someone_else(client):
    """Both directions must agree.

    Alice reserved her match for Bob. Carol naming Alice must NOT land in it —
    a one-sided check (`my target == the creator`) would hand Carol a duel
    Alice never agreed to.
    """
    alice, bob, carol = Account.create(), Account.create(), Account.create()
    ha, hc = _session(client, alice), _session(client, carol)
    a_addr, b_addr = alice.address.lower(), bob.address.lower()

    r = client.post("/api/queue", json={"stake": 1.0, "opponent": b_addr}, headers=ha)
    reserved = r.json()["matchId"]

    r = client.post("/api/queue", json={"stake": 1.0, "opponent": a_addr}, headers=hc)
    assert r.json()["matchId"] != reserved


def test_a_player_cannot_challenge_themselves(client):
    alice = Account.create()
    ha = _session(client, alice)
    r = client.post(
        "/api/queue",
        json={"stake": 1.0, "opponent": alice.address.lower()},
        headers=ha,
    )
    assert r.status_code == 400, r.text
