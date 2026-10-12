"""H22 regression — a session must be revocable.

Audit H22: `auth.revoke_session(jti)` exists, is documented as the F-06
mitigation ("a leaked token can be killed by the owner/operator"), and is
called from nowhere. There is no logout endpoint, so the mitigation is
unreachable through the API: a stolen session token is valid for its full
two-hour TTL with no way to kill it.

The test drives the real HTTP surface: authenticate, log out, then confirm the
same token is rejected.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main as server  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    yield


def _token(client: TestClient, account: Account) -> str:
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": "pulsar.test"})
    message = r.json()["message"]
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify",
        json={"message": message, "signature": sig},
        headers={"host": "pulsar.test"},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_logout_endpoint_exists(client):
    """There must be a way to kill a session through the API."""
    routes = {getattr(r, "path", "") for r in server.app.routes}
    assert "/api/auth/logout" in routes, (
        "no logout route — auth.revoke_session() is unreachable, so a leaked "
        "token survives its full 2h TTL (audit H22)"
    )


def test_a_revoked_session_is_rejected(client):
    """The token must stop working immediately after logout."""
    token = _token(client, Account.create())
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers)
    assert r.status_code == 200, f"a fresh session must work: {r.text}"

    r = client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200, r.text

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers)
    assert r.status_code == 401, (
        f"the revoked token still authenticates (got {r.status_code}) — logout "
        "is cosmetic (audit H22)"
    )


def test_logout_requires_a_valid_session(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 401

    r = client.post("/api/auth/logout", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_logout_does_not_affect_another_session(client):
    """Revoking one token must not revoke a different one."""
    alice, bob = Account.create(), Account.create()
    token_a = _token(client, alice)
    token_b = _token(client, bob)

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

    r = client.post("/api/queue", json={"stake": 1.0}, headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 200, "logging out one session revoked another"

    assert auth.verify_session(token_a) is None
    assert auth.verify_session(token_b) is not None
