"""Audit H-04 (2026-10-22) — the public log must carry what the feed displays.

The lobby feed is built from `/api/settlements`. Before this change the endpoint
published the winner's address but not the two validated times or the prize, so
any feed built on it would have had to invent them — the exact fabrication class
the project's own honesty gates exist to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

WINNER = "0x" + "aa" * 20
LOSER = "0x" + "bb" * 20


@pytest.fixture
def client():
    return TestClient(server.app)


def _settled_match():
    import match_engine as engine

    m = engine.Match(
        match_id="c" * 32,
        stake=5.0,
        created_at=1000.0,
        status="settled",
        creator=WINNER,
        joiner=LOSER,
        players={WINNER: {"address": WINNER}, LOSER: {"address": LOSER}},
    )
    m.winner = WINNER
    m.settled_at = 1200.0
    m.signed_settlement = {
        "status": "settled",
        "winner": WINNER,
        "winnerTimeMs": 210,
        "loserTimeMs": 340,
        "oracleAddress": "0x" + "cc" * 20,
        "signature": "0xdeadbeef",
        "deadline": 2000,
    }
    return m


def test_the_log_publishes_both_times_and_the_real_prize(client, monkeypatch):
    monkeypatch.setattr(server.store, "settled_matches", lambda limit=50: [_settled_match()])

    r = client.get("/api/settlements?limit=5")

    assert r.status_code == 200
    entry = r.json()["settlements"][0]
    assert entry["winnerTimeMs"] == 210
    assert entry["loserTimeMs"] == 340
    # 2 x 5 USDT pool, 2% fee => 9.80, computed with the same integer math as
    # the ledger and the contract.
    assert entry["prize"] == 9.8


def test_the_log_stays_public_and_never_500s(client, monkeypatch):
    def _boom(**_k):
        raise RuntimeError("store down")

    monkeypatch.setattr(server.store, "settled_matches", _boom)

    r = client.get("/api/settlements")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["settlements"] == []
