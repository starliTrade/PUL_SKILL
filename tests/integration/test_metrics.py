"""
Phase 6 / 6.1 — metrics that answer "how well", not just "is it up".

`/api/health` answers "is it up". It cannot answer "how well":

  - **per-endpoint latency** — a queue poll that takes 4s is "up" and useless;
  - **Firestore read count per match** — the cost driver, and the number that
    says whether the design scales (the plan's target is <20 reads per match);
  - **signature failure rate** — a failing oracle means winners cannot claim,
    and it looks identical to a quiet period from the outside;
  - **rate-limiter fallback rate** — already counted, but only as a total, with
    no sense of how often relative to traffic.

The design constraint that matters most: this must be CHEAP. A metrics layer
that adds a Firestore write per request would cost more than it saves, so
everything here is in-process and bounded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


def _metrics(client) -> dict:
    r = client.get("/api/metrics")
    assert r.status_code == 200, r.text
    return r.json()


# --- the four questions -------------------------------------------------------
def test_metrics_report_per_endpoint_latency(client):
    # Generate some traffic first.
    for _ in range(3):
        client.get("/api/health")

    body = _metrics(client)
    assert "endpoints" in body
    health = body["endpoints"].get("GET /api/health")
    assert health is not None, "no latency recorded for a route that was called"
    assert health["count"] >= 3
    for key in ("p50Ms", "p95Ms", "maxMs"):
        assert key in health
        assert health[key] >= 0


def test_metrics_report_firestore_reads_per_match(client):
    body = _metrics(client)

    assert "firestore" in body
    assert "reads" in body["firestore"]
    assert "readsPerMatch" in body["firestore"], (
        "the plan's cost target (<20 reads per match) is unverifiable without this"
    )


def test_metrics_report_signature_failures(client):
    body = _metrics(client)

    assert "signatures" in body
    assert "attempted" in body["signatures"]
    assert "failed" in body["signatures"]
    assert "failureRate" in body["signatures"]


def test_metrics_report_rate_limiter_pressure(client):
    body = _metrics(client)

    assert "rateLimit" in body
    assert "fallbacks" in body["rateLimit"]
    assert "fallbackRate" in body["rateLimit"]


# --- the constraint: it must be cheap -----------------------------------------
def test_metrics_do_not_grow_without_bound(client):
    """An unbounded per-route map is a memory leak with extra steps."""
    for i in range(50):
        client.get(f"/api/does-not-exist-{i}")

    body = _metrics(client)
    assert len(body["endpoints"]) <= server.METRICS_MAX_ROUTES, (
        "the endpoint map grew past its bound — a scanner would leak memory"
    )


def test_metrics_itself_is_not_tracked(client):
    """Otherwise every scrape perturbs the numbers it reports."""
    _metrics(client)
    _metrics(client)
    body = _metrics(client)

    assert "GET /api/metrics" not in body["endpoints"]


def test_metrics_never_leak_a_secret(client):
    raw = client.get("/api/metrics").text.lower()
    for needle in ("oracle_signing_secret", "session_secret", "private", "bearer"):
        assert needle not in raw, f"/api/metrics leaked {needle!r}"
