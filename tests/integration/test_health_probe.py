"""The health probe must ANSWER, even when the server is misconfigured.

Audit 2026-10-13 (found by the phase-10 load run): `/api/health` called
`oracle_address()` unguarded, and `load_signer()` raises when
ORACLE_PRIVATE_KEY is absent — so the probe returned 500. An orchestrator
reads that as a crashed container and restarts it, turning "the oracle key is
missing" into a crash loop instead of the one fact the operator needs.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

API_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "api")


@pytest.fixture()
def client_without_oracle_key(monkeypatch):
    """A server with no ORACLE_PRIVATE_KEY — the misconfigured case."""
    monkeypatch.setenv("PULSAR_ENV", "dev")
    monkeypatch.setenv("ORACLE_SIGNING_SECRET", "0x" + "11" * 32)
    monkeypatch.delenv("ORACLE_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    monkeypatch.delenv("ESCROW_RPC_URL", raising=False)
    monkeypatch.delenv("ALLOWED_DOMAIN", raising=False)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("PULSAR_MATCH_STORE", raising=False)

    sys.path.insert(0, os.path.abspath(API_DIR))
    for mod in ("main", "store", "oracle", "onchain", "economy", "auth", "metrics"):
        sys.modules.pop(mod, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def test_health_answers_when_the_oracle_key_is_missing(client_without_oracle_key):
    res = client_without_oracle_key.get("/api/health")
    assert res.status_code == 200, (
        f"the health probe returned {res.status_code} for a misconfigured server — "
        "an orchestrator would restart the container instead of reporting the cause"
    )
    body = res.json()
    assert body["ok"] is True
    # The misconfiguration is REPORTED rather than raised.
    assert body["oracleAddress"] is None
    assert body["oracleConfigured"] is False
