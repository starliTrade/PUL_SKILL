"""Audit H-05 (2026-10-22) — the player's profile must survive a refresh.

The client wrote `users/{address}` directly; `firestore.rules` denies every
client write, so the tag and friend list were never stored and the error was a
`console.warn`. Worse, the settlement ledger writes that same document, so after
a player's first settled duel the next load returned the LEDGER document (no
`savedFriends`) and replaced the local list with nothing.

The profile now lives in its own collection, written by the server for the
authenticated caller.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
import profiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADDR = "0x" + "11" * 20
FRIEND = "0x" + "22" * 20


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def _memory(monkeypatch):
    monkeypatch.setattr(profiles, "_memory", {})
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    yield


def test_a_saved_friend_survives_a_reload(client):
    r = client.put("/api/profile", json={"savedFriends": [FRIEND]})
    assert r.status_code == 200, r.text

    again = client.get("/api/profile").json()

    assert again["savedFriends"] == [FRIEND], (
        "a saved friend did not survive — the original defect (audit H-05)"
    )


def test_omitted_fields_are_not_cleared(client):
    client.put("/api/profile", json={"playerId": "Duelist_1", "savedFriends": [FRIEND]})
    r = client.put("/api/profile", json={"savedFriends": []})
    body = r.json()
    assert body["playerId"] == "Duelist_1", "an unrelated update cleared the tag"
    assert body["savedFriends"] == []


def test_a_player_cannot_be_their_own_friend(client):
    r = client.put("/api/profile", json={"savedFriends": [ADDR]})
    assert r.status_code == 400


def test_a_free_text_friend_is_refused(client):
    r = client.put("/api/profile", json={"savedFriends": ["not-an-address"]})
    assert r.status_code == 400


def test_an_invalid_tag_is_refused(client):
    r = client.put("/api/profile", json={"playerId": "no spaces allowed"})
    assert r.status_code == 400


def test_an_unreadable_profile_is_a_503_not_an_empty_profile(client, monkeypatch):
    class _Broken:
        def collection(self, *_a, **_k):
            raise RuntimeError("firestore down")

    monkeypatch.setattr(profiles, "_client", lambda: _Broken())

    r = client.get("/api/profile")

    assert r.status_code == 503, (
        "a read failure was reported as an empty profile, which the client would "
        "have used to overwrite the local friend list (audit H-05)"
    )
