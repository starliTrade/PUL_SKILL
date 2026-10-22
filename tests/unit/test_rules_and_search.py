"""Audit M-19 (2026-10-22) — the client must not read the ledger collection.

`users/*` is the settlement ledger: address, wins, XP, reaction averages,
history. It was `allow read: if true` so the friend search could render a card,
which made every player's economic profile enumerable and let a cheater scout an
opponent's reaction average before picking a stake.

The search moved to an authenticated server endpoint that returns five display
fields. These tests pin both halves: the rules are closed, and the endpoint does
not hand back the rest of the document.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import store as store_module  # noqa: E402

ADDR = "0x" + "11" * 20


def test_the_users_collection_is_not_client_readable():
    rules = (ROOT / "firestore.rules").read_text(encoding="utf-8")
    block = rules[rules.index("match /users/{userId}") :]
    block = block[: block.index("match /matches/")]
    assert "allow read: if false;" in block, (
        "users/* is the settlement ledger and is world-readable again (M-19)"
    )
    # Only the COMMENT may mention the old policy; the rule itself must not.
    assert not re.search(r"^\s*allow read: if true", block, re.MULTILINE)


def test_the_username_registry_is_not_client_readable():
    rules = (ROOT / "firestore.rules").read_text(encoding="utf-8")
    block = rules[rules.index("match /usernames/") :]
    assert "allow read: if false;" in block


def test_the_leaderboard_stays_public_because_it_is_pseudonymous():
    rules = (ROOT / "firestore.rules").read_text(encoding="utf-8")
    block = rules[rules.index("match /leaderboard/") : rules.index("match /rate_limits/")]
    assert "allow read: if true;" in block


def test_search_returns_only_display_fields(monkeypatch):
    full_ledger_row = {
        "address": ADDR,
        "playerId": "Nova",
        "level": 4,
        "wins": 9,
        "totalMatches": 12,
        # Everything below must NOT leave the server.
        "avgReactionMs": 188.0,
        "bestReactionMs": 151.0,
        "vaultBalance": 42.5,
        "history": [{"id": "m1"}],
    }

    class _Doc:
        def get(self):
            return type("S", (), {"exists": True, "to_dict": lambda _: dict(full_ledger_row)})()

    class _Col:
        def document(self, _id):
            return _Doc()

        def where(self, *_a, **_k):
            raise AssertionError("address search must not scan")

    class _Db:
        def collection(self, _name):
            return _Col()

    monkeypatch.setattr(store_module, "durable_db", lambda: _Db())
    monkeypatch.setattr(server, "_auth", lambda _r: ADDR)
    monkeypatch.setattr(server, "_rl_check", lambda *a, **k: None)

    body = TestClient(server.app).get(f"/api/players/search?q={ADDR}").json()

    assert len(body["players"]) == 1
    assert set(body["players"][0]) == {
        "address",
        "playerId",
        "level",
        "wins",
        "totalMatches",
    }


def test_search_requires_a_session():
    r = TestClient(server.app).get(f"/api/players/search?q={ADDR}")
    # No Authorization header ⇒ the auth dependency refuses before any query.
    assert r.status_code in (401, 403, 422)
