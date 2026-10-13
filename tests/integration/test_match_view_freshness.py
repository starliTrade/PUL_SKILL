"""M10 — `match_view` must re-read after finalizing, or it serves a stale status.

Audit M10: `match_view` read the match, called `_finalize_if_due(match)` (which
settles it through `store.update`), then returned `match.public_view()` on the
object it had read BEFORE the settlement.

In memory mode `store.get` hands back the stored object, so the mutation is
visible by accident — which is why the bug never showed locally. On Firestore
the store's read-modify-write is ISOLATED: `store.update` reads and writes its
own copy, so the caller's object keeps the pre-settlement status. A player
whose poll just settled the match was told "active" — and the client's refresh
recovery branches on exactly that status.

The store double below reproduces Firestore's isolation: `get()` returns a
copy. That is the only difference from memory mode, and it is the difference
the bug depends on.
"""

from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import main as server  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import match_engine as engine  # noqa: E402


class _CopyIsolatedStore:
    """Firestore read-modify-write semantics: `get()` hands back a COPY.

    A mutation performed through `update()` is therefore invisible to an
    object read earlier — exactly the isolation memory mode does not have.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def get(self, match_id: str):
        return copy.deepcopy(self._inner.get(match_id))  # type: ignore[attr-defined]

    def update(self, match_id: str, mutate):
        return self._inner.update(match_id, mutate)  # type: ignore[attr-defined]

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


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


def test_match_view_reflects_the_settlement_it_just_triggered(client, monkeypatch, clock):
    alice, bob = Account.create(), Account.create()
    _, headers_a = _session(client, alice)
    _, headers_b = _session(client, bob)

    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_a)
    assert r.status_code == 200, r.text
    match_id = r.json()["matchId"]
    r = client.post("/api/queue", json={"stake": 1.0}, headers=headers_b)
    assert r.json()["matchId"] == match_id

    # No rounds played. Past the grace window every unplayed round is a
    # forfeit, so the match becomes decidable — and the READ path is the thing
    # that finalizes it.
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 5)

    monkeypatch.setattr(server, "store", _CopyIsolatedStore(server.store))

    r = client.get(f"/api/match/{match_id}", headers=headers_a)
    assert r.status_code == 200, r.text
    assert r.json()["status"] != "active", (
        "match_view served the pre-settlement status: the poll settled the match "
        "but returned the object it read before the settlement (audit M10)"
    )
