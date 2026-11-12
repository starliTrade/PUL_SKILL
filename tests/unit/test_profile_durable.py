"""Audit L-02 — `savedFriends` must really be STORED, not just held in memory.

`tests/integration/test_profile.py` proves the HTTP round-trip, but it runs
against `profiles._memory` because no Firestore client is configured. The
production branch (`client.collection(...).document(...).set()` / `.get()`) was
therefore never exercised — and that is exactly the branch the audit found
broken: the old code wrote `users/{address}` from the browser, the rules denied
it, and nothing said so.

This test drives `profiles` against a fake client shaped like the Firestore API
the module actually calls, so a wrong collection name, a missing field or a
one-way write fails here instead of on a player's phone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import profiles  # noqa: E402

ME = "0x" + "11" * 20
FRIEND = "0x" + "22" * 20


class _Snap:
    def __init__(self, data: dict | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return None if self._data is None else dict(self._data)


class _Doc:
    def __init__(self, db: _Db, key: str) -> None:
        self._db = db
        self._key = key

    def get(self) -> _Snap:
        return _Snap(self._db.docs.get(self._key))

    def set(self, data: dict) -> None:
        self._db.writes.append((self._key, dict(data)))
        self._db.docs[self._key] = dict(data)


class _Coll:
    def __init__(self, db: _Db, name: str) -> None:
        self._db = db
        self._name = name

    def document(self, key: str) -> _Doc:
        self._db.names.add(self._name)
        return _Doc(self._db, f"{self._name}/{key}")


class _Db:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.writes: list[tuple[str, dict]] = []
        self.names: set[str] = set()

    def collection(self, name: str) -> _Coll:
        return _Coll(self, name)


@pytest.fixture
def db(monkeypatch):
    fake = _Db()
    monkeypatch.setattr(profiles, "_client", lambda: fake)
    monkeypatch.setattr(profiles, "_memory", {})
    return fake


def test_friends_are_written_to_the_profiles_collection(db):
    profiles.update(ME, saved_friends=[FRIEND])
    assert db.names == {"pulsar_profiles"}
    assert len(db.writes) == 1
    key, data = db.writes[0]
    assert key == f"pulsar_profiles/{ME}"
    assert data["savedFriends"] == [FRIEND]
    assert data["address"] == ME
    assert isinstance(data["updatedAt"], int)


def test_a_second_process_reads_the_same_friends(db):
    """The memory dict is wiped between these calls — only the fake DB survives,
    which is what a second replica (or a reload) actually sees."""
    profiles.update(ME, saved_friends=[FRIEND])
    profiles._memory.clear()
    again = profiles.get(ME)
    assert again["savedFriends"] == [FRIEND]


def test_a_patch_does_not_erase_what_it_does_not_mention(db):
    profiles.update(ME, saved_friends=[FRIEND])
    profiles.update(ME, player_id="Nova_1")
    _key, data = db.writes[-1]
    assert data["playerId"] == "Nova_1"
    assert data["savedFriends"] == [FRIEND]


def test_an_empty_list_is_a_real_answer_not_a_missing_field(db):
    profiles.update(ME, saved_friends=[FRIEND])
    profiles.update(ME, saved_friends=[])
    profiles._memory.clear()
    assert profiles.get(ME)["savedFriends"] == []


def test_garbage_already_in_the_document_is_dropped_on_read(db):
    """A hand-edited or legacy document must not crash the profile page."""
    db.docs[f"pulsar_profiles/{ME}"] = {
        "address": ME,
        "savedFriends": ["not-an-address", FRIEND, FRIEND.upper().replace("0X", "0x")],
    }
    assert profiles.get(ME)["savedFriends"] == [FRIEND]


def test_a_player_cannot_save_themselves_on_the_durable_path(db):
    with pytest.raises(profiles.ProfileError):
        profiles.update(ME, saved_friends=[ME])
    assert db.writes == []


def test_more_than_the_cap_is_refused_before_it_is_written(db):
    too_many = ["0x" + f"{i:040x}" for i in range(profiles.MAX_FRIENDS + 1)]
    with pytest.raises(profiles.ProfileError):
        profiles.update(ME, saved_friends=too_many)
    assert db.writes == []
