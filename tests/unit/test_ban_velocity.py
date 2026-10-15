"""Bans and velocity limits (plan item 11.3 / G6).

Two different problems, and conflating them is how anti-abuse becomes
anti-player:

  * a **ban** is a decision about a PERSON — an operator, with a reason, for a
    period. It must be auditable.
  * a **velocity limit** is a decision about a PATTERN — automatic, temporary,
    and deliberately generous, because a fast human and a bot look identical in
    a single sample.

These tests pin that separation, and the default: not banned, no velocity block,
so nothing that exists today changes behaviour.

Isolation note, learned in G3: the controls are DURABLE, so each test takes a
unique address. A fixture that resets one of two stores is not a reset.
"""
from __future__ import annotations

import os

import abuse
import pytest
import timebase


@pytest.fixture
def player() -> str:
    """A UNIQUE address per test — the records are durable, not just in-process."""
    return "0x" + os.urandom(20).hex()


def _travel(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    target = timebase.now() + seconds
    monkeypatch.setattr(timebase, "now", lambda: target)


def test_the_default_is_not_banned(player: str) -> None:
    state = abuse.state(player)
    assert state["banned"] is False
    assert state["velocityBlocked"] is False
    abuse.require(player)  # must not raise


def test_a_ban_refuses_and_expires(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    abuse.ban(player, 3600, "chargeback fraud")
    state = abuse.state(player)
    assert state["banned"] is True
    assert state["banReason"] == "chargeback fraud"
    with pytest.raises(abuse.AbuseError, match="suspended"):
        abuse.require(player)

    _travel(monkeypatch, 3601)
    assert abuse.state(player)["banned"] is False
    abuse.require(player)  # must not raise


def test_a_ban_REQUIRES_a_reason(player: str) -> None:
    """An unexplained ban is not auditable — and an operator who cannot explain
    a ban cannot defend it."""
    with pytest.raises(abuse.AbuseError, match="must carry a reason"):
        abuse.ban(player, 3600, "")
    with pytest.raises(abuse.AbuseError, match="must carry a reason"):
        abuse.ban(player, 3600, "   ")


def test_a_ban_needs_a_positive_duration(player: str) -> None:
    with pytest.raises(abuse.AbuseError, match="positive duration"):
        abuse.ban(player, 0, "because")


def test_unban_lifts_it_immediately(player: str) -> None:
    """An operator must be able to correct a mistake without waiting."""
    abuse.ban(player, 86400, "false positive")
    assert abuse.state(player)["banned"] is True
    abuse.unban(player)
    assert abuse.state(player)["banned"] is False
    abuse.require(player)


def test_velocity_trips_only_after_the_threshold(player: str) -> None:
    """Deliberately generous: this stops a script, not a keen player."""
    for _ in range(abuse.VELOCITY_MAX_MATCHES - 1):
        abuse.note_start(player)
    assert abuse.state(player)["velocityBlocked"] is False
    abuse.require(player)  # must not raise

    abuse.note_start(player)  # the one that trips it
    assert abuse.state(player)["velocityBlocked"] is True
    with pytest.raises(abuse.AbuseError, match="cooldown"):
        abuse.require(player)


def test_velocity_is_temporary_not_a_ban(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The distinction that matters: a pattern check must never be permanent."""
    for _ in range(abuse.VELOCITY_MAX_MATCHES):
        abuse.note_start(player)
    assert abuse.state(player)["velocityBlocked"] is True
    assert abuse.state(player)["banned"] is False, "a velocity trip must not be a ban"

    _travel(monkeypatch, abuse.VELOCITY_COOLDOWN_SECONDS + 1)
    assert abuse.state(player)["velocityBlocked"] is False
    abuse.require(player)  # must not raise


def test_the_velocity_window_slides(player: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Starts older than the window do not count — otherwise a long session
    would eventually block a legitimate player."""
    for _ in range(abuse.VELOCITY_MAX_MATCHES - 1):
        abuse.note_start(player)
    _travel(monkeypatch, abuse.VELOCITY_WINDOW_SECONDS + 1)
    # The old starts have aged out, so this one is not the one that trips it.
    abuse.note_start(player)
    assert abuse.state(player)["velocityBlocked"] is False
    assert abuse.state(player)["recentStarts"] == 1
