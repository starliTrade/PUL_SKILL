"""
Phase 7 / M2 + M3 — the nonce window and the burn's error handling.

**M2.** `_burn_nonce` wraps the durable `create()` in `except Exception: return
False`. Every failure is therefore reported as "already burned" — a replay. A
transient Firestore blip, a permission error or a malformed document all look
identical to a replay, and the operator sees a login failure with no way to tell
which it was. The distinction matters: a replay is an ATTACK, a transient error
is an OUTAGE, and they call for different responses.

**M3.** `_fresh_window` accepts ONLY the exact issuance window. A nonce issued in
the last seconds of a window fails if it is verified in the next one — a random
login failure with no cause the user can act on. The burn is what prevents
replay; the window is only a staleness bound, so a short grace for the previous
window costs nothing and removes the race.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import timebase  # noqa: E402

import auth  # noqa: E402


@pytest.fixture
def clock(monkeypatch):
    class _Clock:
        def __init__(self) -> None:
            self.offset = 0.0

        def advance(self, seconds: float) -> None:
            self.offset += seconds

    c = _Clock()
    base = timebase.now()
    monkeypatch.setattr(timebase, "now", lambda: base + c.offset)
    return c


# --- M3: the boundary race ----------------------------------------------------
def test_a_nonce_issued_at_the_window_edge_is_still_accepted(clock):
    """The last second of a window must not be a coin flip."""
    window = auth.NONCE_WINDOW_SECONDS
    # Move to 1 second before the boundary, then issue.
    clock.advance(window - (timebase.now() % window) - 1)
    nonce = auth.issue_nonce("0x" + "11" * 20, "localhost")

    assert auth.nonce_is_fresh(nonce), "fresh at issuance"

    # Two seconds later we are in the NEXT window.
    clock.advance(2)

    assert auth.nonce_is_fresh(nonce), (
        "a nonce issued one second before the boundary was rejected two seconds "
        "later — the user sees a random login failure (audit M3)"
    )


def test_the_grace_is_bounded(clock):
    """It is a grace, not an unlimited window."""
    window = auth.NONCE_WINDOW_SECONDS
    clock.advance(window - (timebase.now() % window) - 1)
    nonce = auth.issue_nonce("0x" + "11" * 20, "localhost")

    # Well past the grace: two full windows later.
    clock.advance(window + auth.NONCE_BOUNDARY_GRACE_SECONDS + 5)

    assert not auth.nonce_is_fresh(nonce), (
        "the grace extended the nonce validity without bound"
    )


def test_a_nonce_from_two_windows_ago_is_rejected(clock):
    window = auth.NONCE_WINDOW_SECONDS
    nonce = auth.issue_nonce("0x" + "11" * 20, "localhost")

    clock.advance(2 * window)

    assert not auth.nonce_is_fresh(nonce)


# --- M2: a transient error is not a replay ------------------------------------
def test_a_transient_burn_error_is_not_reported_as_a_replay(monkeypatch):
    """The two failure modes must be distinguishable."""
    calls: list[str] = []

    class _Boom(Exception):
        pass

    class _FakeDoc:
        def create(self, _payload):
            raise _Boom("firestore unavailable")

    class _FakeCollection:
        def document(self, _key):
            return _FakeDoc()

    class _FakeDb:
        def collection(self, _name):
            return _FakeCollection()

    monkeypatch.setattr(auth, "_durable_backend", lambda: _FakeDb())
    monkeypatch.setattr(auth, "_log_burn_error", lambda exc: calls.append(repr(exc)))

    before = auth.nonce_burn_errors()
    result = auth._burn_nonce("some-nonce")

    # It must still fail CLOSED — an unverifiable burn cannot authenticate.
    assert result is False
    # ...but it must be RECORDED as an error, not silently counted as a replay.
    assert auth.nonce_burn_errors() > before, (
        "a transient burn failure was reported as a replay with no record — an "
        "outage looks like an attack (audit M2)"
    )
    assert calls, "the error was swallowed without being logged"
