"""
Phase 7 / M11 + M14 — who may claim, and a queue that ignores the stake.

**M11.** `claim_match` verifies the tx really settled this match with the event's
winner equal to `match.winner` — but it never checks that the CALLER is that
winner. The loser can therefore POST a claim and have `onChain: true` recorded
against the match. The money is not at risk (the tx is real and pays the winner),
but the record is wrong: the ledger now says the loser claimed, and any support
investigation starts from a false fact.

**M14.** `queue` returns the live match when the stake matches, and otherwise
falls through to `enqueue` — which is idempotent and returns the SAME live match.
So a player with a live 1-USDT match who queues at 5 USDT silently gets their
1-USDT match back, and the client's UI shows a stake the player did not choose.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


# --- M14 ----------------------------------------------------------------------
def test_queueing_at_a_different_stake_is_refused_not_silently_ignored(client, monkeypatch):
    """The player asked for 5 USDT and has a live 1 USDT match."""
    import store as store_module

    live = store_module.Match(
        match_id="a" * 32,
        stake=1.0,
        created_at=0.0,
        status="waiting",
        creator="0x" + "11" * 20,
    )
    live.players["0x" + "11" * 20] = {"address": "0x" + "11" * 20, "joinedAt": 0.0}
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: live)

    # Authenticate as that player.
    monkeypatch.setattr(server, "_auth", lambda _r: "0x" + "11" * 20)

    r = client.post("/api/queue", json={"stake": 5.0})

    assert r.status_code == 409, (
        f"queueing at 5 USDT while a 1 USDT match is live answered {r.status_code} "
        "— the requested stake was silently ignored (audit M14)"
    )


def test_queueing_at_the_same_stake_still_replays(client, monkeypatch):
    """The control: a re-poll at the same stake returns the live match."""
    import store as store_module

    live = store_module.Match(
        match_id="a" * 32,
        stake=1.0,
        created_at=0.0,
        status="waiting",
        creator="0x" + "11" * 20,
    )
    live.players["0x" + "11" * 20] = {"address": "0x" + "11" * 20, "joinedAt": 0.0}
    monkeypatch.setattr(server.store, "player_live_match", lambda _a: live)
    monkeypatch.setattr(server, "_auth", lambda _r: "0x" + "11" * 20)

    r = client.post("/api/queue", json={"stake": 1.0})

    assert r.status_code == 200


# --- M11 ----------------------------------------------------------------------
def test_the_loser_cannot_record_a_claim(client, monkeypatch):
    """Only the winner may mark a match claimed."""
    import store as store_module

    winner = "0x" + "11" * 20
    loser = "0x" + "22" * 20
    m = store_module.Match(
        match_id="b" * 32,
        stake=1.0,
        created_at=0.0,
        status="settled",
        winner=winner,
    )
    m.players[winner] = {"address": winner, "joinedAt": 0.0}
    m.players[loser] = {"address": loser, "joinedAt": 0.0}

    monkeypatch.setattr(server.store, "get", lambda _mid: m)
    monkeypatch.setattr(server, "_auth", lambda _r: loser)
    # The on-chain verification would SUCCEED (the tx is real and pays the
    # winner) — which is exactly why the caller check has to exist.
    monkeypatch.setattr(server.onchain, "verify_settlement_tx", lambda *a, **k: True)
    recorded: list[str] = []
    monkeypatch.setattr(server.economy, "record_claim", lambda *a, **k: recorded.append("x") or True)

    r = client.post(
        "/api/match/" + "b" * 32 + "/claim",
        json={"txHash": "0x" + "ab" * 32},
    )

    assert r.status_code == 403, (
        f"the LOSER recorded a claim ({r.status_code}) — the ledger now says the "
        "wrong player claimed (audit M11)"
    )
    assert not recorded, "a claim was persisted for a non-winner"


def test_the_winner_can_record_a_claim(client, monkeypatch):
    """The control: the winner's claim still works."""
    import store as store_module

    winner = "0x" + "11" * 20
    m = store_module.Match(
        match_id="c" * 32,
        stake=1.0,
        created_at=0.0,
        status="settled",
        winner=winner,
    )
    m.players[winner] = {"address": winner, "joinedAt": 0.0}

    monkeypatch.setattr(server.store, "get", lambda _mid: m)
    monkeypatch.setattr(server, "_auth", lambda _r: winner)
    monkeypatch.setattr(server.onchain, "verify_settlement_tx", lambda *a, **k: True)
    monkeypatch.setattr(server.economy, "record_claim", lambda *a, **k: True)

    r = client.post(
        "/api/match/" + "c" * 32 + "/claim",
        json={"txHash": "0x" + "ab" * 32},
    )

    assert r.status_code == 200
    assert r.json()["onChainProof"] is True
