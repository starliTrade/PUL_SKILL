"""M9 — the settlement body must raise a DOMAIN error, not an HTTPException.

Audit M9: `_settle_once` raised `HTTPException(409)` from inside the store
mutation. That callback runs inside `store.update`, which on Firestore is a
transaction — a persistence layer that cannot classify a web-framework
exception, and every non-HTTP caller (the lazy finalizer, the re-sign sweep)
has to import the web layer just to catch it. The engine already has the right
error type: `MatchError`.

The HTTP contract does not change: a refused settlement is still 409. What
changes is WHERE the translation happens — at the endpoint, not in the store.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import main as server  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import match_engine as engine  # noqa: E402
from match_engine import MatchError  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    """Force the server onto a clean IN-MEMORY store for this module."""
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    return server.store


def _session(client: TestClient, account: Account) -> tuple[str, dict[str, str]]:
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
    return r.json()["token"], {"Authorization": f"Bearer {r.json()['token']}"}


def test_settle_once_raises_a_domain_error_not_an_http_error(store, active_match):
    """A refused settlement is a MatchError — the store layer never sees HTTP."""
    m = store.get(active_match.match_id)
    with pytest.raises(MatchError):
        server._settle_once(m, engine)


def test_settle_once_never_leaks_a_web_layer_exception(store, active_match):
    m = store.get(active_match.match_id)
    try:
        server._settle_once(m, engine)
    except MatchError:
        pass
    except HTTPException as exc:  # the bug
        pytest.fail(
            "_settle_once raised a web-layer exception from inside the store "
            f"mutation: {exc!r} (audit M9)"
        )


def test_settle_endpoint_still_answers_409_when_settlement_is_refused(client):
    """The HTTP contract is unchanged: a refused settlement is 409, not 500."""
    alice, bob = Account.create(), Account.create()
    _, headers_a = _session(client, alice)
    _, headers_b = _session(client, bob)

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_a)
    assert r.status_code == 200, r.text
    match_id = r.json()["matchId"]
    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_b)
    assert r.json()["matchId"] == match_id

    # No rounds played and the grace window has not passed → settle refuses.
    r = client.post(f"/api/match/{match_id}/settle", headers=headers_a)
    assert r.status_code == 409, r.text
