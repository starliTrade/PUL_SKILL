"""Audit L-09 — a dispute report had no state and no answer to the player.

`POST /api/dispute` stored a row, printed a line, and returned `ok: true`. From
then on the player had no way to learn whether anyone had read it, and an
operator had no way to say which report they had answered: every report was
anonymous and permanent. "Under review" was a promise with no mechanism behind
it.

What this module pins:
  1. filing returns an identity the player can come back with;
  2. only a participant can read the reports for a match (404 for anyone else);
  3. an admin decision lands ON the report and in the admin audit trail;
  4. the decision is visible to the reporter through the status endpoint;
  5. answering a dispute never touches match state or the money path;
  6. an unavailable store is reported, never swallowed into a cheerful `ok`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import timebase  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import match_engine as engine  # noqa: E402
import store as store_module  # noqa: E402

HOST = {"host": "pulsar.test"}
ADMIN = {"X-Admin-Secret": "test-admin-secret"}


def _session(client: TestClient, account: Account) -> dict[str, str]:
    addr = account.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers=HOST)
    message = r.json()["message"]
    sig = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post(
        "/api/auth/verify", json={"message": message, "signature": sig}, headers=HOST
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def server(monkeypatch):
    import main as server_module

    monkeypatch.setattr(server_module.store, "_fs_store", None)
    monkeypatch.setattr(server_module, "_ADMIN_SECRET", ADMIN["X-Admin-Secret"])
    server_module.store.memory.matches.clear()
    server_module.store.memory.queue.clear()
    server_module.store.memory.player_match.clear()
    server_module.store.disputes.clear()
    return server_module


@pytest.fixture
def match(server):
    """A finished, settled duel between two fresh players."""
    alice, bob = Account.create(), Account.create()
    client = TestClient(server.app)
    m = engine.Match(match_id="ab" * 16, stake=1.0, created_at=timebase.now() - 600)
    m.players = {
        alice.address.lower(): {"address": alice.address.lower(), "joinedAt": 0.0},
        bob.address.lower(): {"address": bob.address.lower(), "joinedAt": 0.0},
    }
    m.creator, m.joiner = alice.address.lower(), bob.address.lower()
    m.status = "settled"
    server.store.memory.matches[m.match_id] = m
    return {
        "id": m.match_id,
        "alice": _session(client, alice),
        "bob": _session(client, bob),
        "stranger": _session(client, Account.create()),
        "client": client,
        "match": m,
    }


# --- 1. filing -----------------------------------------------------------------
def test_filing_returns_an_id_the_player_can_come_back_with(match):
    r = match["client"].post(
        "/api/dispute",
        json={"matchId": match["id"], "reason": "the timer froze on round 2"},
        headers={**match["alice"], **HOST},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["disputeId"], "the player has no id to reference"
    assert body["status"] == "open"


def test_a_non_participant_cannot_file_or_read(match):
    r = match["client"].post(
        "/api/dispute",
        json={"matchId": match["id"], "reason": "not my match"},
        headers={**match["stranger"], **HOST},
    )
    assert r.status_code == 404, "a stranger must not learn the match exists"

    r = match["client"].get(f"/api/dispute/{match['id']}", headers={**match["stranger"], **HOST})
    assert r.status_code == 404


# --- 2. reading ---------------------------------------------------------------
def test_the_reporter_can_read_the_status_of_their_own_report(match):
    match["client"].post(
        "/api/dispute",
        json={"matchId": match["id"], "reason": "froze on round two"},
        headers={**match["alice"], **HOST},
    )
    r = match["client"].get(f"/api/dispute/{match['id']}", headers={**match["alice"], **HOST})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    report = body["disputes"][0]
    assert report["status"] == "open"
    assert report["reason"] == "froze on round two"
    assert report["resolution"] is None


def test_a_participant_sees_only_their_own_report(match):
    for who, reason in (("alice", "my side"), ("bob", "the other side")):
        match["client"].post(
            "/api/dispute",
            json={"matchId": match["id"], "reason": reason},
            headers={**match[who], **HOST},
        )
    body = match["client"].get(
        f"/api/dispute/{match['id']}", headers={**match["alice"], **HOST}
    ).json()
    assert [d["reason"] for d in body["disputes"]] == ["my side"], (
        "one player must not read the other's report"
    )


def test_status_of_a_match_with_no_report_is_an_empty_list_not_a_404(match):
    # "I never filed" and "this match does not exist" are different answers.
    r = match["client"].get(f"/api/dispute/{match['id']}", headers={**match["alice"], **HOST})
    assert r.status_code == 200
    assert r.json() == {"matchId": match["id"], "count": 0, "disputes": []}


def test_a_malformed_match_id_is_422(match):
    r = match["client"].get("/api/dispute/not-a-match-id", headers={**match["alice"], **HOST})
    assert r.status_code == 422


# --- 3. answering --------------------------------------------------------------
def _file(match, reason: str = "the timer froze") -> str:
    r = match["client"].post(
        "/api/dispute",
        json={"matchId": match["id"], "reason": reason},
        headers={**match["alice"], **HOST},
    )
    assert r.status_code == 200, r.text
    return r.json()["disputeId"]


def test_an_admin_decision_lands_on_the_report(match, server):
    dispute_id = _file(match)
    r = match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "resolved", "note": "match re-timed; prize stands"},
        headers={**ADMIN, **HOST},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"

    body = match["client"].get(
        f"/api/dispute/{match['id']}", headers={**match["alice"], **HOST}
    ).json()
    report = body["disputes"][0]
    assert report["status"] == "resolved"
    assert report["resolution"] == "match re-timed; prize stands"
    assert report["resolvedAt"]


def test_the_decision_is_in_the_admin_audit_trail(match, server):
    dispute_id = _file(match)
    match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "dismissed", "note": "no evidence of a fault"},
        headers={**ADMIN, **HOST},
    )
    entries = match["client"].get("/api/admin/audit", headers={**ADMIN, **HOST}).json()["entries"]
    decisions = [e for e in entries if e.get("action") == "dispute.resolve"]
    assert decisions, "an operator decision about a payout must be on the record"
    assert dispute_id in decisions[0]["target"]
    assert "dismissed" in decisions[0]["detail"]


def test_resolving_requires_the_admin_secret(match):
    dispute_id = _file(match)
    r = match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "resolved", "note": "x"},
        headers={**match["alice"], **HOST},
    )
    assert r.status_code in (403, 404)


def test_an_unknown_dispute_id_is_404_not_a_silent_success(match):
    r = match["client"].post(
        f"/api/admin/dispute/{match['id']}/{'0' * 32}",
        json={"status": "resolved", "note": "x"},
        headers={**ADMIN, **HOST},
    )
    assert r.status_code == 404


def test_only_the_two_decisions_are_accepted(match):
    dispute_id = _file(match)
    r = match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "refund-him", "note": "x"},
        headers={**ADMIN, **HOST},
    )
    assert r.status_code == 422


# --- 4. it never touches the money path ---------------------------------------
def test_answering_a_dispute_cannot_change_the_match(match, server):
    before = (match["match"].status, match["match"].winner, dict(match["match"].players))
    dispute_id = _file(match)
    match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "resolved", "note": "players were both fine"},
        headers={**ADMIN, **HOST},
    )
    after = (match["match"].status, match["match"].winner, dict(match["match"].players))
    assert after == before, "a review decision must not settle, void or re-pair a duel"


def test_the_endpoints_never_call_a_settlement_or_payout_helper():
    # A source-level guard, because the property is "these functions do not
    # reach the money path at all" — a behavioural test only proves it for the
    # one state it set up.
    source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    for name in ("def report_dispute(", "def dispute_status(", "def admin_resolve_dispute("):
        start = source.index(name)
        end = source.index("\n@app.", start)
        body = source[start:end]
        for forbidden in ("settle_match", "refund", "_pay", "economy.record", "matches["):
            assert forbidden not in body, f"{name} reaches the money path via {forbidden}"


# --- 5. an unavailable store is not a cheerful ok -----------------------------
def test_a_failed_store_write_is_a_503_not_a_false_accept(match, monkeypatch):
    def _boom(_match_id, _report):
        raise store_module.DisputeStoreUnavailable("firestore down")

    # The endpoint must tell the player the report was NOT stored.
    import main as server_module

    monkeypatch.setattr(server_module.store, "record_dispute", _boom)
    r = match["client"].post(
        "/api/dispute",
        json={"matchId": match["id"], "reason": "still frozen"},
        headers={**match["alice"], **HOST},
    )
    assert r.status_code == 503
    assert "could not be stored" in r.json()["detail"]
    assert r.headers.get("retry-after") == "10"


def test_a_failed_resolution_is_a_503_and_says_the_report_is_still_open(match, monkeypatch):
    dispute_id = _file(match)
    import main as server_module

    def _boom(*_a, **_k):
        raise store_module.DisputeStoreUnavailable("firestore down")

    monkeypatch.setattr(server_module.store, "resolve_dispute", _boom)
    r = match["client"].post(
        f"/api/admin/dispute/{match['id']}/{dispute_id}",
        json={"status": "resolved", "note": "x"},
        headers={**ADMIN, **HOST},
    )
    assert r.status_code == 503
    assert "still open" in r.json()["detail"]
