"""The endpoint that failed 157 times out of 157 at 1000 concurrent pollers.

Audit 2026-10-14, found by the load run: Firestore's transaction helper gives up
after five attempts and raises a plain `ValueError`. `/api/queue` let it escape,
so the client got **HTTP 500** — "this is broken, do not retry" — for a request
that was perfectly fine and would have succeeded a second later.

The fix exists in two places and only one of them had a test:

* `_store_contention_handler` (the app-wide exception handler) turns it into a
  retryable 503, and is exercised through the HTTP suite;
* the `queue` endpoint itself catches it *before* the handler and raises
  `HTTPException(503, Retry-After)`, with a comment explaining that the earlier
  fix covered only this route.

The endpoint branch is what actually runs for the busiest route in the product,
and it had no test: `docs/COVERAGE-REPORT.md §3.3` listed those 19 lines as
"testable" while everything around them was either covered or environmental.
This closes that row — the last one the report named as reachable but untested.

The three cases are the whole contract: a busy store is a 503 the client can
retry, a real bug is still a bug (re-raised, not disguised as capacity), and a
matchmaking error keeps its 409 with the message the player can act on.
"""

from __future__ import annotations

from types import SimpleNamespace

import main as server
import pytest
from fastapi import HTTPException

from match_engine import MatchError

ADDRESS = "0x" + "11" * 20


@pytest.fixture()
def endpoint(monkeypatch):
    """`queue()` with every dependency replaced, so only the error mapping is left."""
    from fastapi import Request  # noqa: PLC0415 - only needed to satisfy the signature

    monkeypatch.setattr(server, "_auth_staked", lambda request: ADDRESS)
    monkeypatch.setattr(server, "_rl_check", lambda *a, **k: None)
    monkeypatch.setattr(server.limits, "require", lambda *a, **k: None)
    monkeypatch.setattr(server.abuse, "require", lambda *a, **k: None)
    monkeypatch.setattr(server.abuse, "note_start", lambda *a, **k: None)
    monkeypatch.setattr(server.store, "sweep_expired", lambda: [])
    monkeypatch.setattr(server, "_resign_stale_settlements", lambda: None)
    monkeypatch.setattr(server.economy, "drain_outbox", lambda store: None)
    monkeypatch.setattr(server.store, "player_live_match", lambda address: None)
    monkeypatch.setattr(server.analytics, "note_person", lambda *a, **k: None)

    def call():
        body = server.QueueRequest(stake=1.0, rttMs=40)
        request = Request(
            {"type": "http", "method": "POST", "path": "/api/queue", "headers": [], "client": ("1.2.3.4", 1)}
        )
        return server.queue(body, request)

    return SimpleNamespace(call=call, monkeypatch=monkeypatch)


def _raising(exc):
    def enqueue(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise exc

    return enqueue


def test_a_busy_store_is_a_retryable_503(endpoint) -> None:
    endpoint.monkeypatch.setattr(
        server.store, "enqueue", _raising(ValueError("Failed to commit transaction in 5 attempts."))
    )

    with pytest.raises(HTTPException) as caught:
        endpoint.call()

    exc = caught.value
    assert exc.status_code == 503, (
        "a busy store answered something other than 503 — 500 tells the client "
        "'do not retry', which is the opposite of the truth"
    )
    assert "busy" in str(exc.detail).lower()
    assert exc.headers == {"Retry-After": "1"}, (
        "no Retry-After: the client backs off on its own only if it is told how long"
    )


def test_a_genuine_failure_is_not_disguised_as_capacity(endpoint) -> None:
    """The other half of the contract, and the one an over-eager fix breaks.

    Converting EVERY exception to 503 would make the whole endpoint retryable and
    hide real defects behind a "try again" that never succeeds.
    """
    endpoint.monkeypatch.setattr(server.store, "enqueue", _raising(RuntimeError("a real bug")))

    with pytest.raises(RuntimeError, match="a real bug"):
        endpoint.call()


def test_a_matchmaking_refusal_keeps_its_409_and_its_message(endpoint) -> None:
    endpoint.monkeypatch.setattr(
        server.store, "enqueue", _raising(MatchError("Opponent is no longer waiting"))
    )

    with pytest.raises(HTTPException) as caught:
        endpoint.call()

    assert caught.value.status_code == 409
    assert "no longer waiting" in str(caught.value.detail), (
        "the detail is what the client shows the player; a generic message here "
        "is a support ticket"
    )


def test_a_successful_enqueue_returns_the_public_view(endpoint) -> None:
    # The control: without it, the three tests above could all pass against an
    # endpoint that raises unconditionally. It also pins WHICH object is
    # returned: the caller's own view, not the internal match record (which
    # carries the opponent's intent hashes and the server's timings).
    seen: list[str] = []

    def public_view(for_address: str) -> dict:
        seen.append(for_address)
        return {"matchId": "abc", "status": "waiting"}

    endpoint.monkeypatch.setattr(
        server.store, "enqueue", lambda *a, **k: SimpleNamespace(public_view=public_view)
    )
    assert endpoint.call() == {"matchId": "abc", "status": "waiting"}
    assert seen == [ADDRESS], "the view was built for somebody else"
