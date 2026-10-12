"""
Phase 6 / 6.2 — /api/health must be enough to debug a stuck match.

The endpoint already reported the ledger, the sweep and the rate limiter. Three
things were missing, and each one is a question an operator asks during an
incident and cannot currently answer from the server:

  - **Is the RPC reachable, and on which chain?** A dead or wrong-chain RPC
    makes every deposit gate fail closed, so duels stop being created — and
    nothing on the health page says so.
  - **What decimals does the payment token report?** Audit H13 made the client
    read this at runtime; the server reads it too, and a mismatch between the
    two is a silent mis-scaling of every stake.
  - **Which oracle address signs settlements?** It is already public (it is in
    every settlement packet), and an operator needs it to confirm the deployed
    contract trusts the key the server actually holds.

None of these may leak a secret: the RPC URL, the signing key and the session
secret must never appear.
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


def _health(client) -> dict:
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    return r.json()


# --- the three additions ------------------------------------------------------
def test_health_reports_rpc_state(client):
    body = _health(client)

    assert "rpc" in body, "an operator cannot tell whether the RPC is reachable"
    rpc = body["rpc"]
    assert set(rpc) >= {"configured", "reachable", "chainId"}
    assert isinstance(rpc["configured"], bool)
    assert isinstance(rpc["reachable"], bool)


def test_health_reports_the_token_decimals(client):
    body = _health(client)

    assert "tokenDecimals" in body, (
        "a decimals mismatch between server and client silently mis-scales every "
        "stake (audit H13) and is invisible without this"
    )
    # None is honest when no token is configured; a number must be plausible.
    assert body["tokenDecimals"] is None or 0 < body["tokenDecimals"] <= 36


def test_health_reports_the_oracle_address(client):
    body = _health(client)

    assert "oracleAddress" in body
    # Public by design: it is in every settlement packet.
    assert body["oracleAddress"] == "" or body["oracleAddress"].startswith("0x")


# --- and it must not leak -----------------------------------------------------
def test_health_never_leaks_a_secret(client):
    """The endpoint is unauthenticated, so anything on it is public."""
    raw = client.get("/api/health").text.lower()

    for needle in (
        "oracle_signing_secret",
        "session_secret",
        "private",
        "api_key",
        "apikey",
        "password",
        "bearer",
    ):
        assert needle not in raw, f"/api/health leaked {needle!r}"


def test_health_does_not_echo_the_rpc_url(client):
    """An RPC URL can carry an API key in its path or query."""
    body = _health(client)
    raw = str(body).lower()

    assert "http://" not in raw and "https://" not in raw, (
        "the health payload contains a URL — an RPC URL can embed a provider key"
    )


# --- the existing contract must survive ---------------------------------------
def test_health_keeps_reporting_what_it_already_did(client):
    body = _health(client)

    for key in ("ok", "service", "rounds", "matchStore", "ledger", "sweep", "rateLimit"):
        assert key in body, f"/api/health stopped reporting {key!r}"
    assert body["ok"] is True
