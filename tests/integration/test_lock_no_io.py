"""H10 regression — no network I/O may run while the store lock is held.

Audit H10: `_verify_deposits_or_void` performs a blocking JSON-RPC read (up to
`RPC_TIMEOUT_SECONDS = 5`) and it was called from INSIDE `store.update`'s mutate
callback. The in-memory store holds ONE global lock for every match, so a single
slow RPC serialized every commit / reveal / submit / settle in the process — and
a caller who forces cache misses (new match ids) or simply a slow RPC stalls all
matchmaking. On Firestore it held an open read-write transaction across socket
I/O, risking ABORTED/deadline and contention on the match document.

The invariant pinned here is precise and deterministic (no timing): when the
gate reads the chain, the store lock must NOT be held.

The gate's inputs — `stake` and `players` — are immutable after activation, so
reading the match once outside the lock and validating that snapshot is safe.
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

import onchain  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    """A clean in-memory store: this test is about lock scope, not persistence."""
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    yield server.store
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()


def _session(client: TestClient, account: Account) -> tuple[str, dict[str, str]]:
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
    return addr, {"Authorization": f"Bearer {r.json()['token']}"}


def _paired_match(client: TestClient) -> tuple[str, str, dict[str, str]]:
    alice, bob = Account.create(), Account.create()
    addr_a, headers_a = _session(client, alice)
    _, headers_b = _session(client, bob)
    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers_a)
    match_id = r.json()["matchId"]
    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers_b)
    assert r.json()["matchId"] == match_id, "the two players did not pair"
    return match_id, addr_a, headers_a


def _active_duel(match_id: str, players: list[str]) -> dict:
    """A duel the gate accepts: ACTIVE, matching stake, matching participants."""
    return {
        "status": onchain.STATUS_ACTIVE,
        "player1": players[0],
        "player2": players[1],
        "stakeAmount": 1_000_000,
        "totalPool": 2_000_000,
        "createdAt": 0,
        "winner": "0x" + "00" * 20,
    }


def test_the_deposit_gate_does_not_run_under_the_store_lock(client, monkeypatch):
    """The chain read must happen BEFORE the lock is taken (audit H10)."""
    match_id, addr_a, headers_a = _paired_match(client)
    match = server.store.get(match_id)
    players = sorted(match.players)

    monkeypatch.setenv("ESCROW_RPC_URL", "http://fake-rpc.invalid")
    monkeypatch.setattr(onchain, "escrow_configured", lambda: True)
    onchain._token_decimals = 6

    lock_states: list[bool] = []

    def probing_duel_info(match_id_arg, **kwargs):
        # The whole point: is the store lock held while we talk to the chain?
        lock_states.append(server.store.memory._lock.locked())
        return _active_duel(match_id_arg, players)

    monkeypatch.setattr(onchain, "duel_info", probing_duel_info)

    r = client.post(
        "/api/round/commit",
        json={"matchId": match_id, "roundIndex": 0, "intentHash": "0x" + "ab" * 32},
        headers=headers_a,
    )
    assert r.status_code == 200, r.text
    assert lock_states, "the deposit gate never ran — the test is not exercising it"

    assert not any(lock_states), (
        "the on-chain deposit gate ran while the store lock was held — one slow "
        "RPC (up to 5s) serializes every match in the process (audit H10)"
    )


def test_a_slow_gate_does_not_block_a_second_match(client, monkeypatch):
    """Behavioural proof: another match proceeds while the first waits on the chain."""
    import threading
    import time

    first_id, _, headers_a = _paired_match(client)
    second_id, _, headers_c = _paired_match(client)

    monkeypatch.setenv("ESCROW_RPC_URL", "http://fake-rpc.invalid")
    monkeypatch.setattr(onchain, "escrow_configured", lambda: True)
    onchain._token_decimals = 6

    def slow_duel_info(match_id_arg, **kwargs):
        if match_id_arg == first_id:
            time.sleep(1.5)  # a slow RPC, only for the first match
        m = server.store.get(match_id_arg)
        return _active_duel(match_id_arg, sorted(m.players))

    monkeypatch.setattr(onchain, "duel_info", slow_duel_info)

    timings: dict[str, float] = {}

    def hit(name: str, match_id: str, headers: dict[str, str]) -> None:
        started = time.monotonic()
        client.post(
            "/api/round/commit",
            json={"matchId": match_id, "roundIndex": 0, "intentHash": "0x" + "cd" * 32},
            headers=headers,
        )
        timings[name] = time.monotonic() - started

    t1 = threading.Thread(target=hit, args=("slow", first_id, headers_a))
    t1.start()
    time.sleep(0.2)  # let the slow one get into its RPC
    t2 = threading.Thread(target=hit, args=("fast", second_id, headers_c))
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert "fast" in timings, "the second match never completed"
    assert timings["fast"] < 1.0, (
        f"the second match took {timings['fast']:.2f}s while the first was waiting "
        "on the chain — the store lock is held across network I/O (audit H10)"
    )
