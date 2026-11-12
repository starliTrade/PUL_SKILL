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


# --- the guards in front of the store ---------------------------------------
#
# These are the answers a player gets when the CONTROLS cannot run — the branch
# that decides whether an outage lifts a limit (a free-for-all) or refuses play.
# They were never executed by a test: `/api/queue` has no HTTP-level test, and
# the integration suites that do reach it run with the controls healthy.
def test_a_limits_store_outage_refuses_staked_play(endpoint) -> None:
    """H-02: "we cannot read your limits" must never mean "you have none"."""

    def down(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise server.limits.StoreUnavailable("the controls are unreadable")

    endpoint.monkeypatch.setattr(server.limits, "require", down)
    with pytest.raises(HTTPException) as caught:
        endpoint.call()
    assert caught.value.status_code == 503, (
        "a store outage answered something other than 503 — if it fell through, "
        "an outage silently lifted the stake limits (H-02)"
    )
    assert "unreadable" in str(caught.value.detail)


def test_a_limit_refusal_is_a_403_with_its_reason(endpoint) -> None:
    def refuse(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise server.limits.LimitError("Your daily staked-play budget is used up")

    endpoint.monkeypatch.setattr(server.limits, "require", refuse)
    with pytest.raises(HTTPException) as caught:
        endpoint.call()
    assert caught.value.status_code == 403
    assert "budget" in str(caught.value.detail)


def test_an_abuse_store_outage_is_retryable_not_a_ban(endpoint) -> None:
    def down(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise server.abuse.StoreUnavailable("the abuse record is unreadable")

    endpoint.monkeypatch.setattr(server.abuse, "require", down)
    with pytest.raises(HTTPException) as caught:
        endpoint.call()
    assert caught.value.status_code == 503, (
        "a 403 here tells the player they are suspended — audit M-03 — when the "
        "truth is 'we could not check, try again in a moment'"
    )
    assert caught.value.headers == {"Retry-After": "5"}


def test_a_ban_is_a_403(endpoint) -> None:
    def banned(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise server.abuse.AbuseError("This address is suspended")

    endpoint.monkeypatch.setattr(server.abuse, "require", banned)
    with pytest.raises(HTTPException) as caught:
        endpoint.call()
    assert caught.value.status_code == 403
    assert "suspended" in str(caught.value.detail)


def test_each_sweep_failure_is_counted_and_none_of_them_fails_the_poll(endpoint) -> None:
    """Three lazy sweeps run on the queue poll (audit H9, H-14, item 5).

    One failing must (a) not break matchmaking and (b) not disappear: the old
    `except: pass` is how a dead prize-rescue sweep looked like a working one.
    """
    server._sweep_failures.clear()
    for key in ("total", "sweep_expired", "resign", "ledger_outbox"):
        server._sweep_failures[key] = 0
    endpoint.monkeypatch.setattr(
        server.store,
        "enqueue",
        lambda *a, **k: SimpleNamespace(public_view=lambda for_address: {"ok": True}),
    )
    endpoint.monkeypatch.setattr(
        server.store, "sweep_expired", lambda: (_ for _ in ()).throw(RuntimeError("sweep1"))
    )
    endpoint.monkeypatch.setattr(
        server, "_resign_stale_settlements", lambda: (_ for _ in ()).throw(RuntimeError("sweep2"))
    )
    endpoint.monkeypatch.setattr(
        server.economy, "drain_outbox", lambda store: (_ for _ in ()).throw(RuntimeError("sweep3"))
    )

    assert endpoint.call() == {"ok": True}, "a failing sweep broke the player's queue poll"

    assert server._sweep_failures["sweep_expired"] == 1
    assert server._sweep_failures["resign"] == 1
    assert server._sweep_failures["ledger_outbox"] == 1
    assert server._sweep_failures["total"] == 3
    assert server.sweep_health()["lastError"]["where"] == "ledger_outbox", (
        "the health payload must name the MOST RECENT failure — it is the only "
        "signal an operator has that the sweeps are dead"
    )


def test_a_failing_note_start_does_not_fail_a_duel_the_player_holds(endpoint) -> None:
    """Audit M-03: the velocity counter moves only when a duel actually opened.

    But the counter is bookkeeping; the player is holding a match now. Losing the
    count is an event, not a 500.
    """
    endpoint.monkeypatch.setattr(
        server.store,
        "enqueue",
        lambda *a, **k: SimpleNamespace(public_view=lambda for_address: {"ok": True}),
    )

    def explode(*a, **k):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise RuntimeError("the abuse collection is down")

    endpoint.monkeypatch.setattr(server.abuse, "note_start", explode)
    emitted: list[tuple[str, dict]] = []
    endpoint.monkeypatch.setattr(
        server.eventlog, "emit", lambda name, **fields: emitted.append((name, fields))
    )

    assert endpoint.call() == {"ok": True}
    assert emitted and emitted[-1][0] == "abuse.note_failed"
    assert emitted[-1][1]["error"] == "RuntimeError"
