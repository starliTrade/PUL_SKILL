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
