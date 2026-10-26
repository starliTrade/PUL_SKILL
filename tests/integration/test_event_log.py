"""Audit M-13 (2026-10-22) — money decisions leave a machine-readable trace.

Before this, a settlement produced `print` lines with no match id, no request id
and no way to join a signature to the request that asked for it. A real dispute
("I won and the payout never came") needs: which match, which winner, which
nonce, which deadline, and did the ledger row land — on one line, greppable.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)  # the signer must be real
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import eventlog  # noqa: E402
import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _events(captured: str) -> list[dict]:
    out = []
    for line in captured.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("component") == "event":
            out.append(payload)
    return out


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("PULSAR_EVENT_LOG", "1")
    eventlog.reset()
    yield
    eventlog.reset()


def test_every_response_carries_a_correlation_id():
    client = TestClient(server.app)
    first = client.get("/api/ping")
    second = client.get("/api/ping")

    assert first.headers.get("x-request-id")
    assert second.headers.get("x-request-id")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_a_supplied_request_id_is_echoed_when_it_is_safe():
    client = TestClient(server.app)
    r = client.get("/api/ping", headers={"X-Request-Id": "abc-123_DEF"})
    assert r.headers.get("x-request-id") == "abc-123_DEF"


def test_a_hostile_request_id_is_replaced_not_logged():
    client = TestClient(server.app)
    hostile = "bad id with spaces and \n newline"
    r = client.get("/api/ping", headers={"X-Request-Id": hostile})
    got = r.headers.get("x-request-id", "")
    assert got and got != hostile
    assert "\n" not in got and " " not in got


def test_emit_is_one_json_line_with_the_correlation_id(capsys):
    token = eventlog.set_correlation("corr-1")
    try:
        eventlog.emit("match.settled", matchId="m" * 32, winner="0x" + "ab" * 20, stake=5)
    finally:
        eventlog.reset_correlation(token)

    captured = capsys.readouterr()
    events = _events(captured.err)
    assert len(events) == 1
    payload = events[0]
    assert payload["event"] == "match.settled"
    assert payload["corr"] == "corr-1"
    assert payload["matchId"] == "m" * 32
    assert payload["stake"] == 5


def test_addresses_are_shortened_in_the_stream(capsys):
    eventlog.emit("settle.served", by="0x" + "cd" * 20)
    payload = _events(capsys.readouterr().err)[0]
    assert payload["by"].startswith("0xcdcd")
    assert payload["by"].endswith("cdcd")
    assert len(payload["by"]) < 20, "a full wallet address must not be logged"


def test_emit_never_raises_on_an_unserialisable_field(capsys):
    class Weird:
        def __str__(self) -> str:
            return "weird"

    eventlog.emit("odd.event", value=Weird(), nested={"a": {1, 2}})
    assert _events(capsys.readouterr().err), "the event should still be written"


def test_events_can_be_silenced_for_tests_that_assert_on_stderr(monkeypatch, capsys):
    monkeypatch.setenv("PULSAR_EVENT_LOG", "0")
    eventlog.emit("quiet.event")
    assert _events(capsys.readouterr().err) == []


def test_the_health_endpoint_exposes_event_counts():
    eventlog.emit("some.event")
    for _ in range(2):
        eventlog.emit("other.event")
    body = TestClient(server.app).get("/api/health").json()
    assert body["events"]["some.event"] >= 1
    assert body["events"]["other.event"] >= 2


# --------------------------------------------------------------------------
# The claim that matters: an actual settlement writes the trace.
# --------------------------------------------------------------------------


def _session(client: TestClient, account) -> tuple[str, dict[str, str]]:
    from eth_account.messages import encode_defunct

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


def _play(client: TestClient, headers: dict[str, str], match_id: str, addr: str, idx: int, ms: float):
    import hashlib
    import time as _time

    intent = "0x" + hashlib.sha256(f"{addr}{idx}{_time.time_ns()}".encode()).hexdigest()
    client.post(
        "/api/round/commit",
        json={"matchId": match_id, "roundIndex": idx, "intentHash": intent},
        headers=headers,
    )
    r = client.post(
        "/api/round/target", json={"matchId": match_id, "roundIndex": idx}, headers=headers
    )
    proof = r.json().get("resultProof", "")

    # Model the wall-clock wait: the claim is measured from target appearance.
    match = server.store.get(match_id)
    rr = match.rounds.get(addr, {}).get(idx)
    if rr and rr.revealed_at:
        rr.revealed_at -= (rr.target_ms + ms) / 1000.0
        server.store.put(match)

    return client.post(
        "/api/round/result",
        json={"matchId": match_id, "roundIndex": idx, "measuredMs": ms, "resultProof": proof},
        headers=headers,
    )


def test_a_real_settlement_is_traceable_end_to_end(monkeypatch, capsys):
    """Play a Bo3 to completion and read the trace.

    This is the claim the audit asked for: for one match, the log shows the
    signature (serverNonce + deadline), the winner, and that the ledger row
    landed — all under the correlation id of the request that caused it.

    The round at which a Bo3 becomes decided is the ENGINE's business, so this
    does not assume which submission settles it: every submission's events are
    captured and the one that produced the settlement is asserted on.
    """
    from eth_account import Account

    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()

    client = TestClient(server.app)
    alice, bob = Account.create(), Account.create()
    _, headers_a = _session(client, alice)
    _, headers_b = _session(client, bob)

    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers_a)
    assert r.status_code == 200, r.text
    match_id = r.json()["matchId"]
    r = client.post("/api/queue", json={"stake": 1.0, "rttMs": 40}, headers=headers_b)
    assert r.json()["matchId"] == match_id

    captured: tuple[str, list[dict]] = ("", [])
    for headers, account, ms in (
        (headers_a, alice, 260.0),
        (headers_b, bob, 300.0),
    ):
        for idx in range(3):
            capsys.readouterr()
            r = _play(client, headers, match_id, account.address.lower(), idx, ms + idx)
            corr = r.headers.get("x-request-id", "")
            events = _events(capsys.readouterr().err)
            if any(e["event"] == "match.settled" for e in events):
                captured = (corr, events)
            if r.status_code != 200:
                break

    corr, events = captured
    assert events, f"the match never settled: {server.store.get(match_id).status}"
    settled = [e for e in events if e["event"] == "match.settled" and e["matchId"] == match_id]
    assert settled, f"no match.settled event for {match_id}: {events}"
    payload = settled[-1]
    assert payload["corr"] == corr, "the event is not joinable to the request that caused it"
    # The event redacts addresses (M-13); it must still identify the WINNER of
    # the match that was actually persisted — that is what a dispute looks up.
    settled_match = server.store.get(match_id)
    assert settled_match.status == "settled"
    assert payload["winner"] == f"{settled_match.winner[:6]}…{settled_match.winner[-4:]}"
    assert payload["nonce"] is not None, (
        "the signature's serverNonce must be in the event — without it a dispute "
        "cannot match a payout to the proof that authorised it"
    )
    assert payload["deadline"]

    ledger = [e for e in events if e["event"] == "ledger.written" and e["matchId"] == match_id]
    assert ledger, "the ledger row landing was not recorded"
