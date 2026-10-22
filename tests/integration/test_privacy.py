"""Audit M-21 (2026-10-22) — export and erase a player's data.

The product stores a wallet address, a tag, a friend list and a reaction-time
history, and offered no way to see or remove any of it (GDPR art. 15/17,
CCPA). These tests pin both halves of the answer, including the honest limit:
settlement records are RETAINED, and the response says so instead of promising
a clean sweep it does not perform.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import integrity  # noqa: E402
import main as server  # noqa: E402
import privacy  # noqa: E402
import profiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADDR = "0x" + "11" * 20
FRIEND = "0x" + "22" * 20


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_rl_check", lambda *a, **k: None)
    monkeypatch.setattr(profiles, "_memory", {})
    monkeypatch.setattr(integrity, "_memory", {})
    monkeypatch.setattr(privacy, "_client", lambda: None)
    yield


def test_export_includes_the_profile_and_the_retention_policy(client=None):
    profiles.update(ADDR, player_id="Nova", saved_friends=[FRIEND])
    body = TestClient(server.app).get("/api/account/export").json()

    assert body["address"] == ADDR
    assert body["profile"]["playerId"] == "Nova"
    assert body["profile"]["savedFriends"] == [FRIEND]
    # The player is told what is kept and why, not just handed a file.
    assert body["retention"]["retained"]


def test_erase_removes_the_tag_friends_and_the_integrity_history():
    profiles.update(ADDR, player_id="Nova", saved_friends=[FRIEND])
    integrity.observe(ADDR, [110.0] * 8, "")

    out = TestClient(server.app).post("/api/account/delete", json={"confirm": "DELETE"}).json()

    assert "profile" in out["removed"]
    assert profiles.get(ADDR).get("playerId") in ("", None)
    assert profiles.get(ADDR).get("savedFriends") == []
    assert ADDR not in integrity._memory


def test_erase_refuses_without_the_literal_confirmation():
    r = TestClient(server.app).post("/api/account/delete", json={"confirm": "yes"})
    assert r.status_code == 422
    # And nothing was erased.
    assert profiles.get(ADDR).get("playerId") in ("", None)


def test_erase_states_what_it_keeps_and_never_claims_more():
    out = TestClient(server.app).post("/api/account/delete", json={"confirm": "DELETE"}).json()
    joined = " ".join(out["retained"])
    assert "settlements" in joined
    assert "leaderboard" in joined
    assert "settlement" in out["note"].lower()


def test_erase_is_recorded_in_the_admin_trail(monkeypatch):
    import auditlog

    monkeypatch.setattr(auditlog, "_memory", [])
    monkeypatch.setattr(auditlog, "_client", lambda: None)
    TestClient(server.app).post("/api/account/delete", json={"confirm": "DELETE"})

    assert auditlog.recent(5)[0]["action"] == "account.erase"
    assert auditlog.recent(5)[0]["actor"] == "player"
