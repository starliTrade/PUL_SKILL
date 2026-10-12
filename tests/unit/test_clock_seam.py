"""Plan item 0.5 — the clock seam.

Acceptance for 0.5: "no direct `time.time()` remains in the engine, and tests
can move time forward without touching match state."

These tests prove both halves. The second half matters because the legacy
suites rewound `Round.revealed_at` to fake elapsed time, which silently hides
bugs where a gate compares against the wrong origin (audit H8 was exactly that
class: a play-expiry clock anchored to the wrong instant).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import timebase

import match_engine as engine

API_DIR = pathlib.Path(engine.__file__).resolve().parent


def test_no_module_reads_the_clock_directly():
    """Every wall-clock read must go through the seam, or tests cannot control it."""
    offenders: list[str] = []
    for path in sorted(API_DIR.glob("*.py")):
        if path.name == "timebase.py":
            continue  # the seam itself is the one allowed caller
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"\btime\.time\(\)", line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "direct clock reads bypass the seam:\n" + "\n".join(offenders)


def test_now_ms_tracks_now():
    assert abs(timebase.now_ms() - int(timebase.now() * 1000)) < 50


def test_advancing_the_clock_expires_a_round(active_match, addr, clock):
    """Time moves forward; the engine observes it. No state was rewritten."""
    engine.commit_intent(active_match, addr, 0, "0x" + "ab" * 32)
    target = engine.reveal_target(active_match, addr, 0)

    # Before the deadline the round is alive.
    assert (clock.value - active_match.rounds[addr][0].revealed_at) < engine.ROUND_EXPIRY_SECONDS

    clock.advance(engine.ROUND_EXPIRY_SECONDS + 1)

    with pytest.raises(engine.MatchError, match="expired"):
        engine.submit_result(active_match, addr, 0, 250.0, target["resultProof"])


def test_advancing_the_clock_opens_the_settle_grace_window(active_match, addr, opp_addr, clock, play_round):
    play_round(active_match, addr, 0, reaction_ms=220.0)
    play_round(active_match, addr, 1, reaction_ms=230.0)

    assert engine.match_completed(active_match) is False
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 1)
    assert engine.match_completed(active_match) is True


def test_clock_does_not_leak_between_tests():
    """Sanity: without the fixture, the clock is the real one."""
    import time

    assert abs(timebase.now() - time.time()) < 1.0
