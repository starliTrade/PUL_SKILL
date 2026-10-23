"""Audit L-07 — analytics measured requests, not people.

The funnel counted `POST /api/match` calls as "queued". A player who polls the
queue 40 times was 40 people. That was bad enough when the numbers were only
read at the end of the month; it is worse now that the same file powers a
public snapshot. The server already knows the address on every authenticated
step, so the fix is a capped set of addresses per step — plus the truncation
flag that keeps a bounded set from lying the way an unbounded one would leak.
"""
from __future__ import annotations

import analytics


def setup_function() -> None:
    analytics.reset_people()


def test_one_person_polling_forty_times_is_one_person() -> None:
    for _ in range(40):
        analytics.note_person("queued", "0xAbC0000000000000000000000000000000000001")
    assert analytics.people_counts()["steps"] == {"queued": 1}


def test_addresses_are_case_and_whitespace_insensitive() -> None:
    analytics.note_person("queued", "0xABC0000000000000000000000000000000000001")
    analytics.note_person("queued", "  0xabc0000000000000000000000000000000000001 ")
    assert analytics.people_counts()["steps"]["queued"] == 1


def test_distinct_people_are_distinct() -> None:
    analytics.note_person("arrived", "0x" + "1" * 40)
    analytics.note_person("arrived", "0x" + "2" * 40)
    analytics.note_person("connected", "0x" + "1" * 40)
    steps = analytics.people_counts()["steps"]
    assert steps == {"arrived": 2, "connected": 1}


def test_the_set_is_capped_and_says_so() -> None:
    for i in range(analytics._MAX_PEOPLE_PER_STEP + 10):
        analytics.note_person("queued", f"0x{i:040x}")
    counts = analytics.people_counts()
    assert counts["steps"]["queued"] == analytics._MAX_PEOPLE_PER_STEP
    # The honest label: this is a lower bound, not a count.
    assert counts["truncated"] == ["queued"]
    assert counts["capPerStep"] == analytics._MAX_PEOPLE_PER_STEP


def test_an_empty_address_is_not_a_person() -> None:
    analytics.note_person("arrived", "")
    analytics.note_person("arrived", "   ")
    assert analytics.people_counts()["steps"] == {}


class _EmptyStore:
    def recent_matches(self, limit: int = 0):  # noqa: ANN001
        return []


def test_the_snapshot_carries_the_people_block_and_the_scope() -> None:
    analytics.note_person("arrived", "0x" + "3" * 40)
    snap = analytics.snapshot(_EmptyStore(), {})
    assert "this process only" in snap["people"]["scope"]
    assert snap["people"]["steps"] == {"arrived": 1}


def test_a_broken_store_does_not_hide_the_people_block() -> None:
    """The people counters come from the process, not the store — a Firestore
    outage must not blank the one number that does not need Firestore."""
    analytics.note_person("arrived", "0x" + "4" * 40)

    class Broken:
        def recent_matches(self, limit: int = 0):  # noqa: ANN001
            raise RuntimeError("firestore down")

    snap = analytics.snapshot(Broken(), {})
    assert snap["available"] is False
    assert snap["reason"] == "RuntimeError"
    assert snap["people"]["steps"] == {"arrived": 1}
