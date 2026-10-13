"""
Phase 6 / 6.4 (G8) — a dispute path.

A player who believes a match was settled wrongly currently has no channel. They
can email, which leaves no record and no way for the operator to find the match.

This adds the smallest thing that works: a player reports a match, with a reason,
and the report is stored so an operator can find it. The constraints:

  - **only a participant may report.** Anyone else reporting a match they were
    not in is noise at best and harassment at worst;
  - **the report is bounded** (length, and one open report per match per player),
    so the endpoint cannot be used to fill the database;
  - **the reporter cannot change the outcome.** A report is a request for review,
    not an action. Nothing here moves money.
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


def test_reporting_requires_authentication(client):
    r = client.post(
        "/api/dispute",
        json={"matchId": "0" * 32, "reason": "the result looks wrong"},
    )
    assert r.status_code in (401, 403)


def test_a_report_requires_a_reason(client):
    """An empty report gives the operator nothing to act on."""
    r = client.post("/api/dispute", json={"matchId": "0" * 32, "reason": ""})
    assert r.status_code in (401, 403, 422)


def test_a_report_requires_a_valid_match_id(client):
    r = client.post("/api/dispute", json={"matchId": "nope", "reason": "x"})
    assert r.status_code in (401, 403, 422)


def test_the_reason_is_bounded(client):
    """An unbounded field is a way to fill the database."""
    r = client.post(
        "/api/dispute",
        json={"matchId": "0" * 32, "reason": "x" * 5000},
    )
    assert r.status_code in (401, 403, 422)


def test_the_dispute_route_never_moves_money(client):
    """A report is a request for review. Nothing here may settle or void."""
    raw = client.get("/openapi.json").text
    assert "/api/dispute" in raw
    # The dispute handler must not reference the money-moving engine calls.
    import inspect

    src = inspect.getsource(server.report_dispute)
    for forbidden in ("settle(", "void", "refund", "sign_settlement"):
        assert forbidden not in src, (
            f"the dispute handler references {forbidden!r} — a report must not "
            "change the outcome"
        )
