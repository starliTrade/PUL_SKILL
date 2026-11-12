"""Audit L-08 — the metrics layer must admit the traffic it could not see.

`METRICS_MAX_ROUTES` bounds the route table on purpose (an unbounded dict is a
memory leak an attacker can drive). The bug was the silence: requests past the
cap were dropped and nothing said so, so `sum(count)` looked like total traffic
while quietly missing whatever arrived after the table filled. These tests pin
the honesty, not just the bound.
"""
from __future__ import annotations

import metrics


def setup_function() -> None:
    metrics.reset()


def test_a_complete_snapshot_says_it_is_complete() -> None:
    metrics.observe_request("GET", "/api/health", 1.0)
    snap = metrics.snapshot()
    assert snap["complete"] is True
    assert snap["routesDropped"] == 0
    assert snap["requestsObserved"] == 1
    assert snap["routesTracked"] == 1
    assert snap["routesCap"] == metrics.METRICS_MAX_ROUTES


def test_filling_the_table_past_the_cap_counts_the_drops() -> None:
    for i in range(metrics.METRICS_MAX_ROUTES + 5):
        metrics.observe_request("GET", f"/api/route-{i}", 1.0)
    snap = metrics.snapshot()
    assert snap["routesTracked"] == metrics.METRICS_MAX_ROUTES
    assert snap["routesDropped"] == 5
    # The whole point: `requestsObserved` is the real total, `endpoints` is not.
    assert snap["requestsObserved"] == metrics.METRICS_MAX_ROUTES + 5
    assert snap["complete"] is False


def test_requests_to_an_already_tracked_route_are_not_dropped_at_the_cap() -> None:
    for i in range(metrics.METRICS_MAX_ROUTES):
        metrics.observe_request("GET", f"/api/route-{i}", 1.0)
    metrics.observe_request("GET", "/api/route-0", 2.0)
    snap = metrics.snapshot()
    assert snap["routesDropped"] == 0
    assert snap["endpoints"]["GET /api/route-0"]["count"] == 2


def test_the_scope_is_stated_so_nobody_reads_a_replica_as_the_fleet() -> None:
    snap = metrics.snapshot()
    assert "per-process" in snap["scope"]


def test_reset_clears_the_new_counters() -> None:
    for i in range(metrics.METRICS_MAX_ROUTES + 1):
        metrics.observe_request("GET", f"/r{i}", 1.0)
    metrics.reset()
    snap = metrics.snapshot()
    assert (snap["requestsObserved"], snap["routesDropped"], snap["routesTracked"]) == (0, 0, 0)
