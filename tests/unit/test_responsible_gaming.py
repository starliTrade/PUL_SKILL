"""Responsible-gaming controls (plan item 11.3 / G3).

Three controls that exist for the PLAYER's sake: a deposit limit, self-exclusion,
and a cool-off. These tests pin the two properties that separate a control from a
decoration:

  * a limit can be LOWERED (or cleared) at any time and RAISED only after a
    delay — a limit a player can raise the moment they want to breach it is not
    a limit;
  * self-exclusion CANNOT be lifted early.

And the default: unlimited, so nothing that exists today changes behaviour.

Two bugs these tests found while they were being written, both now fixed and
pinned below: clearing a limit was treated as "raising" and silently delayed, and
`timebase` has no override API — the honest way to travel is to patch the function
the module actually calls.
"""
from __future__ import annotations

import os

import limits
import pytest
import timebase


@pytest.fixture
def player() -> str:
    """A UNIQUE address per test.

    Audit 2026-10-15: the first version reused `0xaa` and cleared only the
    in-process map — but the controls are DURABLE, so a self-exclusion written by
    one test was still there for the next, and the cool-off test failed with
    "you have self-excluded, 23h remaining". A fixture that resets one of two
    stores is not a reset.
    """
    return "0x" + os.urandom(20).hex()


def _travel(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Move the clock forward through the seam that exists.

    `timebase` exposes `now()` and nothing else — there is no override API — so
    the honest way to travel is to patch the function the module actually calls.
    """
    target = timebase.now() + seconds
    monkeypatch.setattr(timebase, "now", lambda: target)


def test_the_default_is_unlimited(player: str) -> None:
    """Nothing that exists today changes behaviour."""
    state = limits.state(player)
    assert state["depositLimit"] is None
    assert state["selfExcluded"] is False
    assert state["coolingOff"] is False
    limits.require(player, 10.0)  # must not raise


def test_a_deposit_limit_refuses_a_stake_above_it(player: str) -> None:
    limits.set_deposit_limit(player, 2.0)
    limits.require(player, 2.0)  # at the limit is allowed
    with pytest.raises(limits.LimitError, match="above your own deposit limit"):
        limits.require(player, 5.0)


def test_lowering_a_limit_is_immediate(player: str) -> None:
    limits.set_deposit_limit(player, 10.0)
    limits.set_deposit_limit(player, 1.0)
    assert limits.state(player)["depositLimit"] == 1.0
    with pytest.raises(limits.LimitError):
        limits.require(player, 2.0)


def test_raising_a_limit_WAITS(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that makes it a limit rather than a suggestion.

    A player who wants to breach their own ceiling can — after a delay they
    cannot shorten. The pending value is visible so the UI can say when.
    """
    limits.set_deposit_limit(player, 1.0)
    state = limits.set_deposit_limit(player, 10.0)
    assert state["depositLimit"] == 1.0, "the raise must not take effect immediately"
    assert state["pendingLimit"] == 10.0
    assert state["pendingLimitAt"] > timebase.now()
    with pytest.raises(limits.LimitError):
        limits.require(player, 5.0)

    _travel(monkeypatch, limits.RAISE_DELAY_SECONDS + 1)
    assert limits.state(player)["depositLimit"] == 10.0
    limits.require(player, 5.0)  # must not raise


def test_clearing_a_limit_is_immediate(player: str) -> None:
    """Removing your own ceiling is not something to slow down.

    A bug this test found: clearing was classified as "raising" (the new value is
    `None`, which is not > current), so it was silently delayed 24 hours — a
    player who wanted to STOP limiting themselves had to wait a day.
    """
    limits.set_deposit_limit(player, 1.0)
    state = limits.set_deposit_limit(player, None)
    assert state["depositLimit"] is None
    assert state["pendingLimit"] is None, "clearing must not schedule anything"
    limits.require(player, 10.0)


def test_self_exclusion_refuses_and_cannot_be_lifted_early(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    limits.self_exclude(player, limits.MIN_EXCLUSION_SECONDS)
    assert limits.state(player)["selfExcluded"] is True
    with pytest.raises(limits.LimitError, match="self-excluded"):
        limits.require(player, 1.0)

    # There is no API that lifts it — the only way out is time. Asserting the
    # ABSENCE of a shortcut is the point of the control.
    assert not hasattr(limits, "clear_exclusion"), (
        "self-exclusion must not have an early-exit function"
    )
    _travel(monkeypatch, limits.MIN_EXCLUSION_SECONDS + 1)
    assert limits.state(player)["selfExcluded"] is False
    limits.require(player, 1.0)  # must not raise


def test_self_exclusion_bounds_are_enforced(player: str) -> None:
    with pytest.raises(limits.LimitError, match="at least"):
        limits.self_exclude(player, 60)
    with pytest.raises(limits.LimitError, match="one year"):
        limits.self_exclude(player, limits.MAX_EXCLUSION_SECONDS + 1)


def test_a_cool_off_is_short_and_expires(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    limits.cool_off(player, 60)
    assert limits.state(player)["coolingOff"] is True
    with pytest.raises(limits.LimitError, match="cool-off"):
        limits.require(player, 1.0)
    _travel(monkeypatch, 61)
    assert limits.state(player)["coolingOff"] is False
    limits.require(player, 1.0)


def test_a_cool_off_cannot_be_used_as_a_long_exclusion(player: str) -> None:
    """The two controls are different on purpose: a cool-off is short."""
    with pytest.raises(limits.LimitError):
        limits.cool_off(player, limits.MAX_COOLOFF_SECONDS + 1)


def test_a_zero_or_negative_limit_is_refused(player: str) -> None:
    with pytest.raises(limits.LimitError, match="greater than zero"):
        limits.set_deposit_limit(player, 0)


# --- Audit H-01 (2026-10-22): an exclusion can only get LONGER ---------------
def test_re_excluding_with_a_shorter_period_does_not_shorten_it(
    player: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The UI promises "cannot be lifted early"; overwriting the end date broke it.

    A player who excluded for a year could call the endpoint again with one day
    and cut their own exclusion by 364 days. The control must be monotonic.
    """
    year = limits.MAX_EXCLUSION_SECONDS
    limits.self_exclude(player, year)
    until = limits.state(player)["excludedUntil"]

    state = limits.self_exclude(player, limits.MIN_EXCLUSION_SECONDS)

    assert state["excludedUntil"] == until, (
        "a second self-exclude call shortened the exclusion (audit H-01)"
    )
    with pytest.raises(limits.LimitError, match="self-excluded"):
        limits.require(player, 1.0)
    _travel(monkeypatch, limits.MIN_EXCLUSION_SECONDS + 1)
    assert limits.state(player)["selfExcluded"] is True


def test_re_excluding_with_a_longer_period_extends_it(player: str) -> None:
    limits.self_exclude(player, limits.MIN_EXCLUSION_SECONDS)
    first = limits.state(player)["excludedUntil"]
    state = limits.self_exclude(player, limits.MIN_EXCLUSION_SECONDS * 2)
    assert state["excludedUntil"] >= first + limits.MIN_EXCLUSION_SECONDS


def test_a_cool_off_cannot_be_shortened_either(player: str) -> None:
    limits.cool_off(player, 3600)
    until = limits.state(player)["cooloffUntil"]
    state = limits.cool_off(player, 60)
    assert state["cooloffUntil"] == until, "a shorter cool-off replaced a longer one"


# --- Audit H-02 (2026-10-22): a store outage fails CLOSED -------------------
def test_an_unreadable_store_refuses_staked_play_instead_of_lifting_limits(
    player: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old fallback resolved an unknown address to "unlimited".

    That means a Firestore hiccup silently removed every self-exclusion and
    deposit ceiling — the failure mode a responsible-gaming control exists to
    prevent.
    """

    class _Broken:
        def collection(self, *_a, **_k):
            raise RuntimeError("firestore unavailable")

    monkeypatch.setattr(limits, "_firestore_client", lambda: _Broken())

    with pytest.raises(limits.StoreUnavailable):
        limits.state(player)
    with pytest.raises(limits.StoreUnavailable):
        limits.require(player, 1.0)
    with pytest.raises(limits.StoreUnavailable):
        limits.self_exclude(player, limits.MIN_EXCLUSION_SECONDS)


# --- Audit M-01 (2026-10-22): reading the controls must not write -----------
def test_reading_state_does_not_persist_a_matured_pending_limit(
    player: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`state()` used to write the matured raise back on a GET."""
    limits.set_deposit_limit(player, 1.0)
    limits.set_deposit_limit(player, 5.0)  # schedules a raise 24h out

    writes: list[str] = []
    real_save = limits._save
    monkeypatch.setattr(limits, "_save", lambda a, d: (writes.append(a), real_save(a, d))[1])

    _travel(monkeypatch, limits.RAISE_DELAY_SECONDS + 1)
    state = limits.state(player)

    assert state["depositLimit"] == 5.0, "the matured raise must be effective"
    assert state["pendingLimit"] is None
    assert writes == [], "a GET persisted state (audit M-01)"
    limits.require(player, 5.0)  # effective without a write
