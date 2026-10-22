"""Audit H-03 (2026-10-22) — measure RTT without chain I/O, and require it.

Two defects in one gate:

1. The client measured its round trip against `/api/health`, whose payload
   performs RPC work (reachability, chain id, decimals). The 400ms ping cap was
   therefore partly a test of the OPERATOR's node, not the player's connection.
2. `rttMs` was optional in `POST /api/queue`, so a client could omit the field
   and skip the cap entirely. A protocol field that can be left out is not a
   gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADDR = "0x" + "11" * 20


@pytest.fixture
def client():
    return TestClient(server.app)


def test_ping_is_zero_io_and_needs_no_session(client, monkeypatch):
    """It must answer even when the store and the chain are unreachable."""

    def _explode(*_a, **_k):
        raise AssertionError("/api/ping touched the store")

    monkeypatch.setattr(server.store, "get", _explode)
    monkeypatch.setattr(server.store, "player_live_match", _explode)
    monkeypatch.setattr(server.onchain, "chain_reachable", _explode)
    monkeypatch.setattr(server.onchain, "token_decimals", _explode)

    r = client.get("/api/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["t"], int) and body["t"] > 0


def test_ping_is_multiple_times_cheaper_than_health(client):
    """Not a benchmark — a structural check that health still does more work.

    The point is that the two endpoints are NOT interchangeable, which is why
    the measurement moved.
    """
    ping = client.get("/api/ping").json()
    assert set(ping) == {"ok", "t"}
    health = client.get("/api/health").json()
    assert "rpc" in health and "tokenDecimals" in health


def test_queue_requires_a_measured_rtt(client, monkeypatch):
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_auth_staked", lambda _r: ADDR)

    r = client.post("/api/queue", json={"stake": 1.0})

    assert r.status_code == 422, (
        "a queue request without rttMs was accepted — the ping cap can be "
        "skipped by omitting the field (audit H-03)"
    )


def test_an_impossibly_high_rtt_is_refused_with_a_clear_message(client, monkeypatch):
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_auth_staked", lambda _r: ADDR)
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: None)

    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 5000})

    assert r.status_code in (409, 422), (
        "a 5-second round trip was allowed into a reaction duel"
    )
