"""The counters an operator reads at 3 a.m. — and the promise that they can't break a request.

Ranked gap #4 in `docs/COVERAGE-REPORT.md`: `metrics.py` lines 99-164. Three
separate concerns, and only the first is about lines:

1. **`observe_request` must never raise.** It is called from the middleware on
   every single request, including the money path. The `except Exception: pass`
   around it is a promise to the caller: a metrics bug becomes a missing data
   point, not a 500. That promise was untested, so it was a comment.
2. **The counters that only /api/metrics consumes had zero callers in the test
   suite** (`note_firestore_read`, `note_firestore_reads_for_route`,
   `note_store_contention`). They are the difference between "47 reads per match"
   and "47 reads per match, and here is which endpoint spends them", and between
   a 503 that means *load* and a 503 that means *breakage*. A rename that
   dropped one of them would have shipped silently.
3. **`_percentile` on an empty list.** Called from `snapshot()` for every route
   with no samples yet; a division-by-zero there would make `/api/metrics`
   fail exactly when traffic has just started.

The lock assertions below are structural on purpose, and say so: `+=` on a
module global is a read-modify-write, so under threads the counter can lose
increments. `tests/unit/test_metrics_bounds_honest.py` covers the *bound*; this
file covers the *attribution*, and the two lock tests pin that the increments
happen inside the same lock `snapshot()` reads under.
"""

from __future__ import annotations

import metrics
import pytest


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # `monkeypatch` is a DEPENDENCY on purpose: a fixture's dependencies are torn
    # down after it, so undo() runs before the teardown `reset()` — which needs
    # the real lock, and one test replaces it with a broken one.
    metrics.reset()
    yield
    monkeypatch.undo()
    metrics.reset()


# --- 1. the middleware promise ------------------------------------------------
class _ExplodingLock:
    """A lock whose acquisition fails — models any bug inside the metrics body."""

    def __enter__(self):
        raise RuntimeError("metrics lock is broken")

    def __exit__(self, *exc):  # noqa: ANN002, ANN003
        return False


def test_observe_request_swallows_its_own_failure(monkeypatch):
    monkeypatch.setattr(metrics, "_lock", _ExplodingLock())
    # The assertion IS that this returns: on a request path this must be a
    # missing data point, never an exception in the response.
    metrics.observe_request("GET", "/api/health", 1.5)


def test_a_dropped_observation_is_not_counted_as_observed(monkeypatch):
    """The counter must not claim a request it failed to record.

    `_requests_observed` is incremented INSIDE the lock, before the work, so this
    is really asserting that the increment is placed where a failure cannot
    leave a half-written entry behind. It runs after the failure above, so a
    counter that leaked past its `except` shows up here.
    """
    metrics.observe_request("GET", "/api/health", 1.0)
    before = metrics.snapshot()["requestsObserved"]
    monkeypatch.setattr(metrics, "_lock", _ExplodingLock())
    metrics.observe_request("GET", "/api/nope", 1.0)
    monkeypatch.undo()
    assert metrics.snapshot()["requestsObserved"] == before


# --- 2. the counters that had no callers -------------------------------------
def test_firestore_reads_are_totalled_and_attributed():
    metrics.note_firestore_read()
    metrics.note_firestore_read(5)
    metrics.note_firestore_reads_for_route("/api/match/{id}", 40)
    metrics.note_firestore_reads_for_route("/api/queue", 2)
    metrics.note_firestore_reads_for_route("/api/match/{id}", 1)

    firestore = metrics.snapshot()["firestore"]
    assert firestore["reads"] == 6
    assert firestore["readsByRoute"] == {"/api/match/{id}": 41, "/api/queue": 2}, (
        "readsByRoute must aggregate per route; a per-request entry per call "
        "would grow with traffic and the top spender would be unreadable"
    )
    # Sorted by spend, so the operator's eye lands on the endpoint to fix first.
    assert list(firestore["readsByRoute"]) == ["/api/match/{id}", "/api/queue"]


def test_non_positive_reads_are_ignored():
    # The middleware measures a delta, and a delta can be 0 (a cached request);
    # recording those would create an entry for every route ever hit.
    metrics.note_firestore_reads_for_route("/api/health", 0)
    metrics.note_firestore_reads_for_route("/api/health", -3)
    assert metrics.snapshot()["firestore"]["readsByRoute"] == {}


def test_reads_per_match_is_none_before_the_first_match():
    metrics.note_firestore_read(10)
    assert metrics.snapshot()["firestore"]["readsPerMatch"] is None, (
        "'no matches yet' must not be reported as '0 reads per match' — that is "
        "the most efficient number possible, for the least data"
    )
    metrics.note_match_settled()
    assert metrics.snapshot()["firestore"]["readsPerMatch"] == 10.0


def test_a_busy_store_is_counted_separately_from_a_broken_one():
    metrics.note_store_contention()
    metrics.note_store_contention()
    assert metrics.snapshot()["store"]["contention503"] == 2


def test_signature_failures_are_visible_as_a_rate():
    metrics.note_signature(True)
    metrics.note_signature(False)
    signatures = metrics.snapshot()["signatures"]
    assert signatures == {"attempted": 2, "failed": 1, "failureRate": 0.5}


def test_no_signature_failure_rate_before_any_attempt():
    assert metrics.snapshot()["signatures"]["failureRate"] is None


# --- 3. the empty-route case in snapshot() ----------------------------------
def test_percentiles_of_a_route_with_no_samples_are_zero_not_an_error():
    # A route is registered by its first observation, so "count > 0, no samples"
    # is not reachable today — but `_percentile` is called with an empty list
    # whenever a route's deque has been drained, and a ZeroDivisionError here
    # would take out the whole /api/metrics payload.
    assert metrics._percentile([], 0.95) == 0.0
    assert metrics._percentile([12.0], 0.99) == 12.0
    assert metrics._percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 3.0  # index = min(int(2), 3)


# --- 4. the lock (structural, and labelled as such) --------------------------
class _RecordingLock:
    def __init__(self):
        import threading

        self._inner = threading.RLock()
        self.acquired = 0

    def __enter__(self):
        self.acquired += 1
        return self._inner.__enter__()

    def __exit__(self, *exc):  # noqa: ANN002, ANN003
        return self._inner.__exit__(*exc)


def test_the_reads_by_route_counter_increments_under_the_lock(monkeypatch):
    """`readsByRoute` is read under `_lock` in `snapshot()`.

    An unlocked `dict[...] = ... + count` racing a `dict(...)` copy in
    `snapshot()` is a "dictionary changed size during iteration" waiting for
    load — the one exception class `observe_request`'s `except` would NOT catch,
    because `snapshot()` has no such guard.
    """
    lock = _RecordingLock()
    monkeypatch.setattr(metrics, "_lock", lock)
    metrics.note_firestore_reads_for_route("/api/queue", 1)
    assert lock.acquired == 1


def test_the_firestore_total_increments_under_the_lock(monkeypatch):
    """Same reasoning for `_firestore_reads`, read inside `snapshot()`'s lock."""
    lock = _RecordingLock()
    monkeypatch.setattr(metrics, "_lock", lock)
    metrics.note_firestore_read(3)
    assert lock.acquired == 1, (
        "the read counter is a read-modify-write on a module global; under "
        "threads an unlocked increment loses counts, and this counter is what "
        "the cost-per-match target is measured with"
    )
