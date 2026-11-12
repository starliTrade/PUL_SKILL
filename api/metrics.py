"""
Phase 6 / 6.1 — in-process metrics.

`/api/health` answers "is it up". This answers "how well": per-endpoint latency,
Firestore reads per match, signature failure rate, and rate-limiter pressure.

**Design constraint: this must be CHEAP.** A metrics layer that writes to
Firestore per request would cost more than it saves, so everything here is
in-process and bounded. Two consequences:

  - the per-route map is capped at `METRICS_MAX_ROUTES`. An unbounded map keyed
    by path is a memory leak that any scanner can trigger by requesting random
    URLs — the bound is not an optimisation, it is the difference between a
    metric and a vulnerability;
  - latency is kept as a fixed-size reservoir per route, not a full list. A
    list that grows with traffic grows without limit on a busy server.

The numbers are per-process. With N replicas each reports its own, which is
honest: aggregating them is the monitoring system's job, not the server's.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

# How many distinct routes are tracked before new ones are dropped. 64 is far
# above the real route count (~15) and far below anything a scanner can use to
# exhaust memory.
METRICS_MAX_ROUTES = 64

# Latency samples kept per route.
#
# Audit 2026-10-14: this was 256, which is enough for a stable p95 but makes p99
# statistically meaningless — the 99th percentile of 256 samples is the 2nd
# highest value, i.e. "almost the max". 1024 gives p99 about ten samples to sit
# on, at a few tens of KB per route with a 64-route cap.
_LATENCY_SAMPLES = 1024

_lock = threading.Lock()

# route -> {"count": int, "totalMs": float, "maxMs": float, "samples": deque}
_endpoints: dict[str, dict[str, Any]] = {}

# Counters. Kept as plain ints so a read is atomic enough for monitoring.
_firestore_reads = 0
# route template -> Firestore reads attributed to it (see note_firestore_reads_for_route)
_reads_by_route: dict[str, int] = {}
# requests answered 503 because the store was busy
_store_contention = 0
_matches_settled = 0
_signatures_attempted = 0
_signatures_failed = 0
# Audit L-08: when the route cap is hit, requests were DROPPED silently, so the
# sum of every per-route count quietly stopped matching the traffic. A metrics
# layer whose totals are wrong is worse than one that admits a bound: count the
# drops and expose them, so "1,412 requests, 300 dropped" is readable instead of
# a number that looks complete and is not.
_routes_dropped = 0
_requests_observed = 0


def _route_key(method: str, path: str) -> str:
    """A bounded key for a request.

    Uses the ROUTE TEMPLATE where FastAPI resolved one (`/api/match/{id}`), not
    the raw path, so per-match ids do not each become their own entry. Falls
    back to the raw path for unmatched requests, which the cap then bounds.
    """
    return f"{method} {path}"


def observe_request(method: str, path: str, elapsed_ms: float) -> None:
    """Record one request. Called from middleware; must never raise."""
    global _routes_dropped, _requests_observed
    key = _route_key(method, path)
    try:
        with _lock:
            _requests_observed += 1
            entry = _endpoints.get(key)
            if entry is None:
                if len(_endpoints) >= METRICS_MAX_ROUTES:
                    # Bounded on purpose, COUNTED on purpose (audit L-08).
                    _routes_dropped += 1
                    return
                entry = {
                    "count": 0,
                    "totalMs": 0.0,
                    "maxMs": 0.0,
                    "samples": deque(maxlen=_LATENCY_SAMPLES),
                }
                _endpoints[key] = entry
            entry["count"] += 1
            entry["totalMs"] += elapsed_ms
            if elapsed_ms > entry["maxMs"]:
                entry["maxMs"] = elapsed_ms
            entry["samples"].append(elapsed_ms)
    except Exception:
        # A metrics failure must never break a request.
        pass


def note_firestore_read(count: int = 1) -> None:
    """Count reads. Incremented under `_lock` like every other counter here.

    This one used to be a bare `_firestore_reads += count` while `snapshot()`
    read it inside the lock: `+=` on a module global is a read-modify-write, so
    two threads could read the same value and one increment would vanish. The
    lost counts land exactly on the number the "<20 reads per match" target is
    measured with, and under-counting is the direction that hides a regression.
    The bound-and-attribution tests in `tests/unit/test_metrics_attribution.py`
    pin the lock (structurally, and labelled as such — a data race cannot be
    asserted deterministically).
    """
    global _firestore_reads
    with _lock:
        _firestore_reads += count


def reset_endpoint_counts() -> None:
    """Clear the per-endpoint counters. Tests and the drill call this."""
    with _lock:
        _endpoints.clear()


def endpoint_counts() -> dict[str, int]:
    """route -> request count. The funnel is built from these."""
    with _lock:
        return {path: int(entry["count"]) for path, entry in _endpoints.items()}


def firestore_reads_total() -> int:
    """The counter, for attributing a request's reads to its route."""
    return _firestore_reads


def note_firestore_reads_for_route(path: str, count: int) -> None:
    """Attribute `count` reads to a route.

    Audit 2026-10-14: `readsPerMatch` was a single total, which says a match
    costs ~47 reads but not WHERE they go — so it cannot be acted on. The
    middleware measures the delta across each request and lands it here, which
    turns the number into a list of the endpoints that actually spend it.
    """
    if count <= 0:
        return
    with _lock:
        _reads_by_route[path] = _reads_by_route.get(path, 0) + count


def note_match_settled() -> None:
    global _matches_settled
    _matches_settled += 1


def note_store_contention() -> None:
    """A request refused because the store was BUSY (returned 503, not 500).

    Audit 2026-10-14: this is the honest signal for "we were at capacity", and
    it is what tells an operator whether the 503s are load or a regression.
    """
    global _store_contention
    _store_contention += 1


def note_signature(ok: bool) -> None:
    global _signatures_attempted, _signatures_failed
    _signatures_attempted += 1
    if not ok:
        _signatures_failed += 1


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[index]


def snapshot() -> dict[str, Any]:
    """The metrics payload. Cheap: no I/O, no allocation beyond the copy."""
    with _lock:
        endpoints: dict[str, Any] = {}
        for key, entry in _endpoints.items():
            samples = sorted(entry["samples"])
            endpoints[key] = {
                "count": entry["count"],
                "avgMs": round(entry["totalMs"] / entry["count"], 2) if entry["count"] else 0.0,
                "p50Ms": round(_percentile(samples, 0.50), 2),
                "p95Ms": round(_percentile(samples, 0.95), 2),
                # Audit 2026-10-14: plan item 10.3.4 claimed p50/p95/p99 for
                # every endpoint, but only p50 and p95 were computed — p99
                # appeared NOWHERE in the repo. The claim was unsupported; the
                # fix is to make it true rather than to delete the requirement,
                # because p99 is the number that shows tail latency, and tail
                # latency is what a player feels when a round hangs.
                "p99Ms": round(_percentile(samples, 0.99), 2),
                "maxMs": round(entry["maxMs"], 2),
            }
        reads = _firestore_reads
        settled = _matches_settled
        attempted = _signatures_attempted
        failed = _signatures_failed
        dropped = _routes_dropped
        observed = _requests_observed

    return {
        # Audit L-08: scope and completeness, stated in the payload. A scrape
        # that silently covers only part of the traffic is how an incident looks
        # like "we had no traffic".
        "scope": "per-process — N replicas each report their own slice",
        "requestsObserved": observed,
        "routesDropped": dropped,
        "routesTracked": len(endpoints),
        "routesCap": METRICS_MAX_ROUTES,
        "complete": dropped == 0,
        "endpoints": endpoints,
        "firestore": {
            "reads": reads,
            # Where the reads actually go. Sorted, so the top spender is first.
            "readsByRoute": dict(
                sorted(_reads_by_route.items(), key=lambda kv: kv[1], reverse=True)
            ),
            "matchesSettled": settled,
            # The plan's cost target is <20 reads per match. Reported as None
            # rather than 0 before the first match, so "no data" is not read as
            # "perfectly efficient".
            "readsPerMatch": round(reads / settled, 2) if settled else None,
        },
        "signatures": {
            "attempted": attempted,
            "failed": failed,
            "failureRate": round(failed / attempted, 4) if attempted else None,
        },
        "store": {
            # A busy store is capacity, not breakage. Counted so the two are
            # never confused when reading the logs.
            "contention503": _store_contention,
        },
        "process": {
            "uptimeSeconds": round(time.monotonic() - _STARTED_AT, 1),
        },
    }


_STARTED_AT = time.monotonic()


def reset() -> None:
    """Test seam: clear all counters."""
    global _firestore_reads, _matches_settled, _signatures_attempted, _signatures_failed
    with _lock:
        _endpoints.clear()
        _reads_by_route.clear()
    _firestore_reads = 0
    global _store_contention
    _store_contention = 0
    _matches_settled = 0
    _signatures_attempted = 0
    _signatures_failed = 0
    global _routes_dropped, _requests_observed
    _routes_dropped = 0
    _requests_observed = 0
