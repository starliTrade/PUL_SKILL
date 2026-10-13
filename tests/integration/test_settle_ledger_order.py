"""H4 regression — the ledger write must happen AFTER the match transaction commits.

Audit H4: `round_result`'s mutate callback called `economy.record_settlement(m)`
INSIDE the store transaction. `record_settlement` performs its own Firestore
writes, so the ledger row is committed independently of the match transaction
that encloses it. If that transaction later aborts (a conflict the retry
resolves, or a commit failure), the ledger records a settlement for a match
that was rolled back.

The invariant this test pins is about ORDER, which is exactly what the fix
changes and exactly what a rolled-back transaction depends on:

    record_settlement must not be invoked from inside store.update's mutate.

Observed with the bug: the ledger event precedes the store.update event.
"""

from __future__ import annotations

import hashlib
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
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    """Force the server onto a clean IN-MEMORY store for this module.

    With FIRESTORE_EMULATOR_HOST set the server boots Firestore-backed, so a
    match left WAITING by another test survives in the emulator and this
    module's two players pair with it instead of each other — which showed up
    as a confusing "matchId mismatch" that only reproduced in the full suite.

    This module is about the ORDER of the ledger write, not about persistence,
    so it gets a clean in-memory store. `_fs_store = None` keeps the existing
    store object (and its installed persistence hooks) and just switches the
    backend.
    """
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    return server.store


def _session(client: TestClient, account: Account) -> tuple[str, dict[str, str]]:
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
    return r.json()["token"], {"Authorization": f"Bearer {r.json()['token']}"}


def _play(client: TestClient, headers: dict[str, str], match_id: str, addr: str, idx: int, ms: float) -> dict:
    intent = "0x" + hashlib.sha256(f"{addr}{idx}{time.time_ns()}".encode()).hexdigest()
    client.post(
        "/api/round/commit",
        json={"matchId": match_id, "roundIndex": idx, "intentHash": intent},
        headers=headers,
    )
    r = client.post("/api/round/target", json={"matchId": match_id, "roundIndex": idx}, headers=headers)
    proof = r.json().get("resultProof", "")

    # Model the wall-clock wait on the server object, exactly as the legacy
    # suite does: the claim is measured from target appearance.
    #
    # Goes through the store abstraction rather than `store.memory.matches`:
    # with FIRESTORE_EMULATOR_HOST set the server boots in Firestore mode, and
    # a rewind applied only to the in-process cache would be invisible to the
    # next request — the round would then be rejected as "submitted before the
    # target was displayed" and the match would never settle.
    match = server.store.get(match_id)
    rr = match.rounds.get(addr, {}).get(idx)
    if rr and rr.revealed_at:
        rr.revealed_at -= (rr.target_ms + ms) / 1000.0
        server.store.put(match)

    r = client.post(
        "/api/round/result",
        json={"matchId": match_id, "roundIndex": idx, "measuredMs": ms, "resultProof": proof},
        headers=headers,
    )
    return r.json() if r.status_code == 200 else {"http": r.status_code, "detail": r.json().get("detail")}


def test_ledger_is_written_after_the_match_transaction_commits(client, monkeypatch):
    """The ledger must not be written from inside store.update's mutate."""
    alice, bob = Account.create(), Account.create()
    token_a, headers_a = _session(client, alice)
    token_b, headers_b = _session(client, bob)

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_a)
    assert r.status_code == 200, r.text
    match_id = r.json()["matchId"]
    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_b)
    assert r.json()["matchId"] == match_id

    # Record the interleaving of the two effects. The buggy version writes the
    # ledger from INSIDE the mutate, so "ledger" lands before "update".
    events: list[str] = []
    real_update = server.store.update
    real_record = economy.record_settlement

    def traced_update(match_id_arg, mutate):
        events.append("update:enter")
        out = real_update(match_id_arg, mutate)
        events.append("update:exit")
        return out

    def traced_record(match):
        events.append("ledger")
        return real_record(match)

    monkeypatch.setattr(server.store, "update", traced_update)
    monkeypatch.setattr(economy, "record_settlement", traced_record)

    # Alice plays all three rounds; Bob plays all three. Bob's final submission
    # completes the Bo3 naturally, which is the path that ledgers.
    for idx in range(3):
        _play(client, headers_a, match_id, alice.address.lower(), idx, 260.0 + idx)
    for idx in range(3):
        _play(client, headers_b, match_id, bob.address.lower(), idx, 300.0 + idx)

    assert "ledger" in events, f"the settlement was never ledgered: {events}"

    ledger_at = events.index("ledger")
    last_exit = max(i for i, e in enumerate(events) if e == "update:exit")
    assert ledger_at > last_exit, (
        "the ledger was written INSIDE the match transaction "
        f"(events: {events}) — a rolled-back settlement would leave a ledger row "
        "for a match that was never settled (audit H4)"
    )
