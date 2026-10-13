"""CRITICAL (audit 2026-10-13) — the durable client must be reachable.

`auth`, `economy` and the username endpoints resolved the Firestore client as
`getattr(store_module, "_fs_store", None)` — a MODULE attribute that never
exists, because `_fs_store` is an INSTANCE attribute of `DurableMatchStore`.

So in production, with Firestore fully configured:
  - the economy ledger never wrote (wins/XP/prize/leaderboard all absent),
  - `GET /api/player/{addr}/stats` always answered `available: false`,
  - `POST /api/match/{id}/claim` reported a VERIFIED claim as unrecorded,
  - SIWE nonce replay protection and session revocation were per-process only,
  - the username registry always answered 503.

The suite hid it two ways: `tests/integration/test_economy_idempotency.py`
monkeypatched the module attribute into existence, and
`scripts/test_firestore_integration.py` printed its ledger step as "skipped"
while counting it as a PASS.

This test builds the store the way PRODUCTION does — `create_store()` against a
real Firestore backend — and asserts the consumers can reach it. It
deliberately does NOT monkeypatch any private attribute: that is exactly what
hid the bug.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)
os.environ.setdefault("PULSAR_ENV", "dev")

pytestmark = pytest.mark.emulator


@pytest.fixture
def durable_store(monkeypatch):
    """A store built exactly the way production builds it."""
    firestore = pytest.importorskip("google.cloud.firestore")
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set — run scripts/start_emulator.sh --bg")
    try:
        probe = firestore.Client(project="demo-pulsar")
        probe.collection("_probe").document("ping").set({"ok": True})
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.skip(f"Firestore emulator unreachable at {host}: {exc}")

    monkeypatch.setenv("PULSAR_MATCH_STORE", "firestore")
    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "demo-pulsar")

    import store as store_module

    s = store_module.create_store()
    assert s.backend_name == "firestore", "the fixture did not reach the durable backend"
    return s


def test_the_economy_can_reach_the_durable_client(durable_store):
    import economy

    assert economy._fs_db() is not None, (
        "the economy ledger cannot see the durable client the store is using — "
        "settlements are never recorded (audit CRITICAL-1)"
    )
    assert economy.ledger_available() is True


def test_auth_can_reach_the_durable_client(durable_store):
    import auth

    assert auth._durable_backend() is not None, (
        "SIWE nonce replay protection and session revocation are per-process "
        "only — a captured login signature replays across replicas "
        "(audit CRITICAL-1)"
    )


def test_the_username_registry_can_reach_the_durable_client(durable_store):
    """A 503 means the registry could not reach Firestore at all."""
    import main as server
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    account = Account.create()
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": "pulsar.test"})
    assert r.status_code == 200, r.text
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
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    r = client.get("/api/username/never-claimed-name", headers=headers)
    assert r.status_code == 200, (
        f"the username registry could not reach the durable store: {r.status_code} {r.text}"
    )
    assert r.json().get("available") is True, r.text
