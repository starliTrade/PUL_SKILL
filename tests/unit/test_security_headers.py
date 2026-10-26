"""Audit H-16 (2026-10-22) — browser hardening headers.

There was no Content-Security-Policy anywhere in the repository. The session
token is in localStorage and the app moves money, so any injected script — a
compromised dependency, a translation string rendered as HTML, a rogue wallet
extension — can read the token and drive the escrow. These headers are enforced
by the browser even when the application code is wrong.

Scope, stated honestly: the API can only set headers on ITS responses. The SPA
is served by the static host, whose headers this repository does not control;
docs/DEPLOYMENT.md §4b carries the exact policy for that host.
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


def test_every_response_carries_the_hardening_headers(client):
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["permissions-policy"]


def test_the_policy_forbids_framing_plugins_and_foreign_scripts(client):
    csp = client.get("/api/ping").headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp, "the app can be framed (clickjacking)"
    assert "object-src 'none'" in csp, "plugins (flash/pdf) are an execution surface"
    assert "base-uri 'self'" in csp, "a <base> tag can redirect every relative URL"
    assert "form-action 'self'" in csp
    # No wildcard script source: that would make the policy decorative.
    assert "script-src 'self'" in csp
    assert "script-src *" not in csp


def test_error_responses_are_hardened_too(client):
    # A 404 is still rendered by the browser's error pipeline.
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"


def test_hsts_is_only_sent_in_a_production_like_environment(monkeypatch):
    # `_prod_like` is computed at import; assert the intended behaviour of the
    # predicate rather than the import-time constant.
    monkeypatch.delenv("PULSAR_ENV", raising=False)
    assert server._is_prod_like({}) is True
    assert server._is_prod_like({"PULSAR_ENV": "dev"}) is False
