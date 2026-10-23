"""Helpers shared by the tests that drive a REAL running API (audit H-22).

Two suites (`test_eligibility_gate.py`, `test_ranked_flow_e2e.py`) sign real SIWE
sessions against `127.0.0.1:8000`. The server allows **10 nonce handshakes per
minute per IP** (`RL_AUTH_MAX`, keyed by IP since audit #8 F-10), and the two
suites together use seven. Running `pytest` twice inside a minute therefore
exhausted the bucket, and the second run failed with

    assert token is not None        # _sign_in returned None

— a rate limit wearing the costume of a broken eligibility gate. That is a test
that only passes when the clock is on its side.

The server already tells clients when to come back (`Retry-After`, audit #7 R3).
These tests now do what a well-behaved client does: wait the advertised time once
and retry. If the bucket is still full afterwards, the failure says so in those
words instead of blaming the product.

The limiter itself is NOT weakened or bypassed: no env flag, no test header, no
bigger limit in the E2E stack. This file only honours the 429 contract.
"""

from __future__ import annotations

import time

# Long enough for a full 60-second window, short enough that a stuck run cannot
# hang a suite for minutes. The server's window is RL_WINDOW_SECONDS = 60.
MAX_WAIT_SECONDS = 70.0


def retry_delay(exc: Exception, cap: float = MAX_WAIT_SECONDS) -> float:
    """Seconds to wait before retrying, from the response's `Retry-After`."""
    headers = getattr(exc, "headers", None)
    raw = ""
    if headers is not None:
        try:
            raw = headers.get("Retry-After", "")
        except Exception:  # noqa: BLE001 — header object of unknown shape
            raw = ""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 5.0
    return max(0.5, min(value, cap))


def wait_and_retry(exc: Exception, retry, cap: float = MAX_WAIT_SECONDS):
    """Honour `Retry-After` and call `retry()` up to three times.

    Three, not one, and measured rather than guessed: one suite makes SIX
    handshakes and the cap is TEN per minute per IP, so running two suites inside
    the same minute can hit a second 429 *after* the first wait — which is what a
    single retry produced (`1 failed, 4 passed in 60.25s`). The loop makes the
    harness behave like a client that keeps its promises without hammering.

    Raises the last exception if all attempts are refused, so the caller still
    sees a 429 rather than a silent success.
    """
    last = exc
    for _ in range(3):
        time.sleep(retry_delay(last, cap))
        try:
            return retry()
        except Exception as again:  # noqa: BLE001 — re-raised below if it is a 429
            code = getattr(again, "code", None) or getattr(again, "status_code", None)
            if code != 429:
                raise
            last = again
    raise last


# --- one session per identity per run (audit H-24) ---------------------------
#
# H-22 taught the live suites to honour `Retry-After`. That was necessary and not
# sufficient: the two live suites signed in SIX times per run against a cap of
# TEN per minute per IP, so two runs inside a minute still collided, and a full
# `pytest` run (which takes 20-80 s and re-runs every suite) walked into the
# ceiling on its own. Measured 2026-10-23: 1 failed / 626 passed, the failure
# being `assert None is not None` in the eligibility suite.
#
# Retrying a global budget is the wrong tool: it turns a shared counter into a
# waiting room. The suites do not need six identities — they need TWO (attested
# and unattested) and the ranked flow needs two FIXED keys. Minting each once per
# process drops the handshake count to four, which fits under the cap with room
# for a second run in the same minute.
#
# This does not weaken anything: the token is still a real SIWE session, the
# server still verifies it on every request, and the limiter still refuses when
# the budget is genuinely exceeded.

_TOKENS: dict[str, str] = {}


def mint_once(key: str, mint) -> str:
    """Return the session for `key`, minting it at most once per process."""
    if key not in _TOKENS:
        _TOKENS[key] = mint()
    return _TOKENS[key]


def reset_sessions() -> None:
    """Forget every cached session (used by the tests of this helper)."""
    _TOKENS.clear()


class SessionUnavailable(RuntimeError):
    """A live session could not be minted — named, never returned as None.

    `assert token is not None` was the old failure mode: the actual cause (a 429
    from a per-IP budget) was invisible, so the failure read as a product bug.
    """
