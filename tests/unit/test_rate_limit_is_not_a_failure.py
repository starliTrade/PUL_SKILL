"""H-22 — a rate limit must not read as a broken feature.

`test_eligibility_gate.py` and `test_ranked_flow_e2e.py` sign real SIWE sessions
against the live API. The server allows **10 nonce handshakes per minute per IP**
(`RL_AUTH_MAX`, keyed by IP since audit #8 F-10) and one suite uses six, so the
second run inside the same minute died with

    assert token is not None

— which reads as "the eligibility gate is broken" and was in fact the server
correctly protecting `/api/auth/nonce`. A test that only passes when the clock is
on its side is not a test.

The suites now behave like a well-behaved client: honour `Retry-After` (the
server already sends it, audit #7 R3) and retry, up to three times.

Two things are deliberately NOT done:
  * the limiter is not weakened, raised, disabled or bypassed for tests — the
    whole point of those suites is to exercise production behaviour;
  * a repeated 429 is not swallowed — after the last attempt the 429 is raised,
    so an actually-exhausted budget fails loudly instead of silently skipping.

Measured after the fix, same stack, two consecutive runs:
    run 1: 5 passed in 0.24 s
    run 2: 5 passed in 60.33 s   (waited out the window instead of failing)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.fixtures.live_api import MAX_WAIT_SECONDS, wait_and_retry  # noqa: E402


class _RateLimited(Exception):
    """Stand-in for urllib's HTTPError: same `headers`/`code` surface."""

    def __init__(self, retry_after: str | None = "2", code: int = 429) -> None:
        super().__init__("rate limited")
        self.code = code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The helper sleeps for the server's window; the test records instead."""
    slept: list[float] = []
    monkeypatch.setattr("tests.fixtures.live_api.time.sleep", lambda s: slept.append(s))
    return slept


def test_the_advertised_wait_is_honoured(_no_real_sleep: list[float]) -> None:
    wait_and_retry(_RateLimited("7"), lambda: "ok")
    assert _no_real_sleep == [7.0], "the server's Retry-After was not used"


def test_a_missing_or_garbage_header_still_backs_off(_no_real_sleep: list[float]) -> None:
    wait_and_retry(_RateLimited(None), lambda: "ok")
    wait_and_retry(_RateLimited("soon"), lambda: "ok")
    assert all(0.5 <= s <= MAX_WAIT_SECONDS for s in _no_real_sleep), _no_real_sleep


def test_the_wait_is_capped_so_a_stuck_run_cannot_hang_a_suite(
    _no_real_sleep: list[float],
) -> None:
    wait_and_retry(_RateLimited("86400"), lambda: "ok")
    assert _no_real_sleep == [MAX_WAIT_SECONDS]


def test_it_retries_after_the_wait(_no_real_sleep: list[float]) -> None:
    calls: list[int] = []

    def _attempt() -> str:
        calls.append(1)
        return "ok"

    assert wait_and_retry(_RateLimited("1"), _attempt) == "ok"
    assert calls == [1]


def test_a_second_rate_limit_is_waited_out_too(_no_real_sleep: list[float]) -> None:
    """Measured case: one suite makes six handshakes against a cap of ten, so a
    second 429 after the first wait is expected — one retry was not enough."""
    attempts: list[int] = []

    def _attempt() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _RateLimited("2")
        return "ok"

    assert wait_and_retry(_RateLimited("2"), _attempt) == "ok"
    assert len(attempts) == 3


def test_an_exhausted_budget_fails_loudly(_no_real_sleep: list[float]) -> None:
    def _always() -> str:
        raise _RateLimited("1")

    with pytest.raises(_RateLimited):
        wait_and_retry(_RateLimited("1"), _always)


def test_a_non_rate_limit_error_is_not_retried(_no_real_sleep: list[float]) -> None:
    """A 500 must surface as a 500, not be slept over."""

    class _Boom(Exception):
        code = 500

    def _attempt() -> str:
        raise _Boom("server error")

    with pytest.raises(_Boom):
        wait_and_retry(_RateLimited("1"), _attempt)


def test_the_live_suites_actually_use_the_helper() -> None:
    for rel in (
        "tests/integration/test_eligibility_gate.py",
        "tests/integration/test_ranked_flow_e2e.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "wait_and_retry" in text, f"{rel} signs in without honouring Retry-After"
        assert "429" in text
