"""Audit H-09 (2026-10-22) — a logout that did not persist must not say "ok".

`revoke_session` swallowed every exception, so a failed Firestore write reported
success while the token stayed valid for the rest of its 2h TTL. This is the one
call a user makes when they believe a device is compromised.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


def _session(client) -> dict[str, str]:
    acct = Account.create()
    addr = acct.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": "pulsar.test"})
    message = r.json()["message"]
    sig = acct.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify",
        json={"message": message, "signature": sig},
        headers={"host": "pulsar.test"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_a_revocation_that_could_not_be_recorded_answers_503(client, monkeypatch):
    headers = _session(client)
    monkeypatch.setattr(server._auth_module, "revoke_session", lambda _jti: False)

    r = client.post("/api/auth/logout", headers=headers, )

    assert r.status_code == 503, (
        "logout reported success while the token stayed valid (audit H-09)"
    )


def test_a_durable_revocation_still_answers_ok(client):
    headers = _session(client)
    r = client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # And the token is dead afterwards.
    assert client.post("/api/auth/logout", headers=headers).status_code == 401
