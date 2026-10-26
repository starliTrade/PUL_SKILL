"""Audit C-01 (2026-10-22) — waiting in the queue must not count as starting duels.

`POST /api/queue` is both "start matchmaking" and "poll while waiting": the
client re-sends the SAME request every 2.5–10s until it pairs. `abuse.note_start`
used to run before the "you already have a live match" early return, so every
poll incremented the velocity counter. With VELOCITY_MAX_MATCHES=20 per 10
minutes, two normal searches (~11 polls each) locked an honest player out for
15 minutes — an anti-abuse control that fired on the honest waiting behaviour it
should encourage, while a bot (which never waits) was unaffected.

The fix moves the counter to the only point that can create or join a duel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import abuse  # noqa: E402
import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADDR = "0x" + "11" * 20


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def _clean_abuse(memory_backends):
    """A counter per test, in the map this module asserts against.

    `abuse._save` writes Firestore AND `_memory` while `_load` prefers
    Firestore, so under the emulator the counter leaked from the previous test
    (same address) and `recentStarts == 0` read as 1 — the L-11 regression this
    test exists to prevent, reported against code that was correct.
    """
    abuse._memory.clear()
    yield
    abuse._memory.clear()


def _live_waiting_match():
    import store as store_module

    m = store_module.Match(
        match_id="b" * 32,
        stake=1.0,
        created_at=0.0,
        status="waiting",
        creator=ADDR,
    )
    m.players[ADDR] = {"address": ADDR, "joinedAt": 0.0}
    return m


def test_forty_queue_polls_do_not_trip_the_velocity_limit(client, monkeypatch):
    """40 polls of a live waiting match must leave the player allowed to play.

    40 is twice the 20-per-10-minutes budget: the old code locked the player
    out at poll #20, i.e. during their second search.
    """
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_auth_staked", lambda _r: ADDR)
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: _live_waiting_match())

    for i in range(40):
        r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40})
        assert r.status_code == 200, f"poll {i + 1} answered {r.status_code}: {r.text}"

    state = abuse.state(ADDR)
    assert state["recentStarts"] == 0, (
        "polling a live match was counted as starting a duel — the velocity "
        f"counter reached {state['recentStarts']} (audit C-01)"
    )
    assert state["velocityBlocked"] is False
    abuse.require(ADDR)  # must not raise


def test_a_genuine_new_match_still_counts(client, monkeypatch):
    """The control: the limit must still see real starts.

    A player with no live match who queues starts a duel — that is the event
    the limit exists for, and removing it would trade a false positive for a
    false negative.
    """
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_auth_staked", lambda _r: ADDR)
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: None)
    monkeypatch.setattr(server.store, "enqueue", lambda *a, **k: _live_waiting_match())

    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40})
    assert r.status_code == 200
    assert abuse.state(ADDR)["recentStarts"] == 1


def test_invalid_stake_is_rejected_before_the_counter_moves(client, monkeypatch):
    """L-11: `ALLOWED_STAKES` was checked AFTER note_start, so a malformed
    request consumed the player's budget without ever being playable."""
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_auth_staked", lambda _r: ADDR)
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: None)

    r = client.post("/api/queue", json={"stake": 3.0, "rttMs": 40})
    assert r.status_code == 400
    assert abuse.state(ADDR)["recentStarts"] == 0
