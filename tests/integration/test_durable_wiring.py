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


def test_a_rate_limit_document_carries_a_ttl_stamp(durable_store):
    """Audit 2026-10-13: nothing ever deleted these rows.

    The distributed limiter writes one document per (bucket, address) and never
    removed any, so `rate_limits` grew without bound on the hottest path. The
    document now carries `expiresAt`, the field a Firestore TTL policy deletes
    on (the policy itself is a deploy step — see docs/DEPLOYMENT.md §3c).
    """
    import main as server

    addr = "0x" + "22" * 20
    server._rl_check("ttl_probe", addr, 1000)

    doc = durable_store._fs_store.db.collection("rate_limits").document(
        f"rl:ttl_probe:{addr}"
    ).get()
    assert doc.exists, "the limiter did not write its document"
    body = doc.to_dict() or {}
    assert "expiresAt" in body, (
        "the rate-limit document has no TTL stamp — the collection grows forever"
    )
    assert body["expiresAt"] is not None


def test_the_username_lookup_does_not_leak_the_owner(durable_store):
    """Audit M12 (2026-10-13): the endpoint returned the owner's wallet address.

    The finding was marked fixed in phase 6.10 and was not — any session holder
    could enumerate names and map them to addresses. The caller now learns only
    whether the name is free, taken, or already theirs.
    """
    import main as server
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from fastapi.testclient import TestClient

    owner = Account.create()
    other = Account.create()
    owner_addr = owner.address.lower()
    db = durable_store._fs_store.db
    db.collection("usernames").document("taken-name").set(
        {"username": "taken-name", "tag": "Taken", "address": owner_addr}
    )

    client = TestClient(server.app)

    def headers_for(account: Account) -> dict[str, str]:
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
        return {"Authorization": f"Bearer {r.json()['token']}"}

    # A stranger asks: no address in the answer.
    body = client.get("/api/username/taken-name", headers=headers_for(other)).json()
    assert body == {"available": False, "username": "taken-name", "taken": True}, body
    assert "owner" not in body, "the lookup still leaks the owner's address (audit M12)"

    # The owner asks: told it is theirs, still without echoing the address.
    body = client.get("/api/username/taken-name", headers=headers_for(owner)).json()
    assert body.get("available") is True and body.get("alreadyOwned") is True, body
    assert "owner" not in body


def test_the_firestore_read_metric_is_actually_counted(durable_store):
    """Audit 2026-10-13: `note_firestore_read` had no caller.

    The "Firestore reads per match" metric (plan item 6.1) therefore reported
    `None` forever — a dashboard field that could never show a number.
    """
    import metrics

    metrics.reset()
    match = durable_store.enqueue("0x" + "66" * 20, 2.0, 20.0)
    before = metrics.snapshot()["firestore"]["reads"]

    durable_store.get(match.match_id)

    after = metrics.snapshot()["firestore"]["reads"]
    assert after > before, "Firestore reads are not counted — readsPerMatch is always None"
