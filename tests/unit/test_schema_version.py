"""Firestore document schema versioning (plan item 6.11 / G16).

Audit 2026-10-15: this item was marked done for months with NO implementation —
`grep -rn schemaVersion api/` found only a comment saying the migration was still
needed. The read path tolerated missing fields, which is NOT versioning:
tolerating a missing field is safe, but nothing stopped old code from silently
misreading a NEWER document by taking the fields it knew and ignoring the rest.

That is the failure these tests exist to prevent, so the most important test here
is the one that proves a future document is REFUSED.
"""
from __future__ import annotations

import pytest

from api.store import (
    SCHEMA_VERSION,
    Match,
    SchemaVersionError,
    _match_from_doc,
    _match_to_doc,
    migrate_document,
)


def _legacy_doc() -> dict:
    """A document as written BEFORE versioning existed."""
    return {
        "match_id": "a" * 32,
        "stake": 1.0,
        "created_at": 100.0,
        "players": {
            "0xaa": {"address": "0xaa", "joinedAt": 1.0},
            "0xbb": {"address": "0xbb", "joinedAt": 2.0},
        },
        "status": "active",
        "rounds": {},
    }


def test_every_written_document_carries_the_version() -> None:
    m = Match(match_id="b" * 32, stake=1.0, created_at=1.0)
    doc = _match_to_doc(m)
    assert doc["schemaVersion"] == SCHEMA_VERSION


def test_a_legacy_document_is_migrated_forward() -> None:
    doc = migrate_document(_legacy_doc())
    assert doc["schemaVersion"] == SCHEMA_VERSION
    # The fields the read path used to DERIVE on the fly are now stamped, so a
    # later reader does not have to reproduce that derivation.
    assert doc["creator"] == "0xaa"
    assert doc["joiner"] == "0xbb"
    assert doc["target"] == ""
    assert doc["min_rtt_ms"] == {}


def test_migration_is_idempotent() -> None:
    once = migrate_document(_legacy_doc())
    twice = migrate_document(dict(once))
    assert once == twice, "migrating twice must not change the document"


def test_a_newer_document_is_REFUSED_not_half_read() -> None:
    """The whole point of versioning.

    A document from a future server has fields this code does not know about.
    Reading it anyway would silently drop them — and the next write would make
    that loss permanent. It must fail loudly instead.
    """
    future = _legacy_doc()
    future["schemaVersion"] = SCHEMA_VERSION + 1
    future["someFutureField"] = {"nested": True}

    with pytest.raises(SchemaVersionError, match="newer than this server"):
        migrate_document(future)
    with pytest.raises(SchemaVersionError):
        _match_from_doc(future)


def test_reading_a_legacy_document_still_works() -> None:
    """Backwards compatibility: old documents must keep being readable."""
    m = _match_from_doc(_legacy_doc())
    assert m.match_id == "a" * 32
    assert m.creator == "0xaa"
    assert m.joiner == "0xbb"
    assert m.status == "active"


def test_a_legacy_document_without_timestamps_refuses_to_guess() -> None:
    """The honest failure mode: an empty creator is visible, a wrong one is not."""
    doc = _legacy_doc()
    doc["players"] = {"0xaa": {"address": "0xaa"}, "0xbb": {"address": "0xbb"}}
    migrated = migrate_document(doc)
    assert migrated["creator"] == ""
    assert migrated["joiner"] == ""
    assert migrated["schemaVersion"] == SCHEMA_VERSION


def test_a_round_trip_preserves_the_version() -> None:
    m = _match_from_doc(_legacy_doc())
    again = _match_from_doc(_match_to_doc(m))
    assert again.match_id == m.match_id
    assert again.creator == m.creator
    assert again.joiner == m.joiner


# --- the creator derivation must not depend on map key order ------------------


def test_creator_is_derived_from_joinedAt_not_key_order() -> None:
    """Firestore does NOT preserve map key order.

    Audit 2026-10-15: writing `{"0xaa": …, "0xbb": …}` and reading it back five
    times returned `('0xbb', '0xaa')` every time — so deriving the creator from
    "the first key" named the WRONG player. In a money game the creator is the
    one who deposits first, so this is not cosmetic.

    This test feeds the players map in BOTH orders and demands the same answer.
    """
    from api.store import _creator_from_players

    first = {"0xaa": {"address": "0xaa", "joinedAt": 1.0}, "0xbb": {"address": "0xbb", "joinedAt": 2.0}}
    reversed_ = {"0xbb": {"address": "0xbb", "joinedAt": 2.0}, "0xaa": {"address": "0xaa", "joinedAt": 1.0}}

    assert _creator_from_players(first) == ("0xaa", "0xbb")
    assert _creator_from_players(reversed_) == ("0xaa", "0xbb"), (
        "the answer must not change with key order"
    )


def test_creator_is_not_guessed_without_timestamps() -> None:
    """No `joinedAt` means no honest answer — so say nothing, not something wrong."""
    from api.store import _creator_from_players

    assert _creator_from_players({"0xaa": {"address": "0xaa"}, "0xbb": {"address": "0xbb"}}) == ("", "")


def test_a_legacy_document_gets_the_right_creator() -> None:
    doc = _legacy_doc()
    doc["players"] = {
        "0xbb": {"address": "0xbb", "joinedAt": 2.0},
        "0xaa": {"address": "0xaa", "joinedAt": 1.0},
    }
    migrated = migrate_document(doc)
    assert migrated["creator"] == "0xaa", "the earliest joiner is the creator"
    assert migrated["joiner"] == "0xbb"
