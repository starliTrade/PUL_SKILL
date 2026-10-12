"""H6 + H7 regression — production configuration must fail closed.

H6: the "this looks like production" check only fired when `PULSAR_ENV` was one
of a fixed set of strings OR one of five platform markers was present. A
self-hosted Docker/VM deployment with no marker and no `PULSAR_ENV` therefore
ran with NO required-env enforcement, wildcard CORS, no TrustedHost middleware,
and a SIWE domain taken from the request's Host header. Fail-open security
configuration.

H7: `_request_domain()` returned the client-controlled `Host` header whenever
`ALLOWED_DOMAIN` was unset. The nonce MAC and the canonical SIWE message are
both bound to that value, so an attacker chose the domain the server issued and
accepted statements for — removing the phishing resistance the design claims.

Both are pinned here as behaviour, not as implementation: an unknown environment
must be treated as production, and a foreign Host header must not become the
SIWE domain.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

from eth_account import Account  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main as server  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


# --- H6: the production predicate --------------------------------------------
def test_an_unknown_environment_is_treated_as_production():
    """The default must be safe: opt OUT of production, never opt in."""
    assert server._is_prod_like({}) is True, (
        "an environment with no PULSAR_ENV and no platform marker was treated "
        "as local dev — a self-hosted deployment silently ran with wildcard "
        "CORS and no required-env enforcement (audit H6)"
    )


def test_production_like_values_are_recognised():
    for value in ("prod", "production", "main", "release", "staging", "Production "):
        assert server._is_prod_like({"PULSAR_ENV": value}) is True, value


def test_platform_markers_are_recognised():
    for marker in ("K_SERVICE", "K_REVISION", "RENDER", "FLY_MACHINE_ID", "DYNO"):
        assert server._is_prod_like({marker: "1"}) is True, marker


def test_local_dev_must_opt_out_explicitly():
    for value in ("dev", "development", "test", "local", "DEV"):
        assert server._is_prod_like({"PULSAR_ENV": value}) is False, value


def test_a_production_deployment_must_configure_itself():
    """Every security-relevant env var is required once production-like."""
    missing = server._missing_production_env({})
    for name in (
        "ALLOWED_DOMAIN",
        "CORS_ALLOW_ORIGINS",
        "ESCROW_ADDRESS",
        "ESCROW_RPC_URL",
        "ORACLE_SIGNING_SECRET",
        "ORACLE_PRIVATE_KEY",
    ):
        assert name in missing, f"{name} is not enforced in production"


def test_a_fully_configured_deployment_has_nothing_missing():
    full = {
        "ALLOWED_DOMAIN": "pulsar.test",
        "CORS_ALLOW_ORIGINS": "https://pulsar.test",
        "ESCROW_ADDRESS": "0x" + "ab" * 20,
        "ESCROW_RPC_URL": "https://rpc.example",
        "ORACLE_SIGNING_SECRET": "s",
        "ORACLE_PRIVATE_KEY": "0x" + "11" * 32,
    }
    assert server._missing_production_env(full) == []


# --- H7: the SIWE domain ------------------------------------------------------
def test_a_foreign_host_header_cannot_pick_the_siwe_domain(client, monkeypatch):
    """The domain the server issues statements for must not be attacker-chosen."""
    monkeypatch.delenv("ALLOWED_DOMAIN", raising=False)
    monkeypatch.setenv("ESCROW_ADDRESS", "0x" + "ab" * 20)
    monkeypatch.setenv("ESCROW_RPC_URL", "https://rpc.example")

    addr = Account.create().address.lower()
    r = client.post(
        "/api/auth/nonce", json={"address": addr}, headers={"host": "attacker.example"}
    )
    assert r.status_code == 200, r.text
    message = r.json()["message"]

    assert "attacker.example" not in message, (
        "the server issued a SIWE statement for the caller's Host header — the "
        "domain binding is client-controlled (audit H7)"
    )


def test_the_configured_domain_wins(client, monkeypatch):
    monkeypatch.setenv("ALLOWED_DOMAIN", "pulsar.test")
    addr = Account.create().address.lower()
    r = client.post(
        "/api/auth/nonce", json={"address": addr}, headers={"host": "attacker.example"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"].startswith("pulsar.test wants you to sign in")
