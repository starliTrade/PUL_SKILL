"""Server-side eligibility gate (plan item 11.3 / G2).

The client has an eligibility gate whose own comment admits the problem:
"Consent is one localStorage key, so clearing storage bypasses it." A gate a
player can remove with a devtools command is not a gate.

These tests pin the SERVER-side property, and one design decision that is easy to
get wrong: the gate is on `/api/queue` (the entry) and NOT on the round, settle or
claim endpoints — because a gate that can strand money is worse than the gap it
closes.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

API = os.environ.get("PULSAR_E2E_API", "http://127.0.0.1:8000")

# Opt OUT of the test-process bypass in conftest: this file exists to exercise
# the REAL gate, so it must not be handed a stubbed one.
pytestmark = pytest.mark.real_eligibility


def _api(path: str, body: dict | None = None, token: str | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    req.add_header("Host", "127.0.0.1:8000")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            # Audit H-22: the server names the wait; honour it once. Without
            # this, running the suite twice inside a minute failed with
            # "assert token is not None" — a rate limit that read as a broken
            # eligibility gate.
            from tests.fixtures.live_api import wait_and_retry  # noqa: PLC0415

            def _again():
                with urllib.request.urlopen(req, timeout=25) as res:
                    return res.status, json.loads(res.read() or b"{}")

            try:
                return wait_and_retry(exc, _again)
            except urllib.error.HTTPError as exc2:
                return exc2.code, json.loads(exc2.read() or b"{}")
        return exc.code, json.loads(exc.read() or b"{}")


def _sign_in(confirm: bool) -> str | None:
    """A live session for the ATT or UNATT state, minted once per run (H-24).

    Six handshakes per run against a 10/min/IP budget made consecutive runs
    collide; the suite only ever needs one identity of each kind.
    """
    from tests.fixtures.live_api import mint_once  # noqa: PLC0415

    return mint_once(f"eligibility:{confirm}", lambda: _mint_session(confirm))


def _mint_session(confirm: bool) -> str | None:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    account = Account.create()
    status, nonce = _api("/api/auth/nonce", {"address": account.address.lower()})
    if status != 200:
        return None
    signature = account.sign_message(encode_defunct(text=nonce["message"])).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    status, verified = _api("/api/auth/verify", {"message": nonce["message"], "signature": signature})
    if status != 200:
        return None
    token = verified["token"]
    if confirm:
        status, _ = _api("/api/eligibility/confirm", {"ageConfirmed": True}, token)
        assert status == 200
    return token


@pytest.fixture(autouse=True)
def _needs_api():
    try:
        status, _ = _api("/api/health")
    except Exception:  # noqa: BLE001
        pytest.skip("no API on 127.0.0.1:8000 — run scripts/start_e2e_stack.sh")
    if status != 200:
        pytest.skip("the API is not healthy")


def test_an_unattested_session_cannot_stake() -> None:
    token = _sign_in(confirm=False)
    assert token is not None
    status, body = _api("/api/queue", {"stake": 1, "rttMs": 40}, token)
    assert status == 403, f"an unattested session must not reach the queue: {status} {body}"
    assert "eligibility" in json.dumps(body).lower()


def test_an_attested_session_can_stake() -> None:
    token = _sign_in(confirm=True)
    assert token is not None
    status, body = _api("/api/queue", {"stake": 1, "rttMs": 40}, token)
    assert status == 200, f"an attested session must reach the queue: {status} {body}"
    assert body.get("status") in ("waiting", "active")


def test_the_gate_is_NOT_on_the_exit_paths() -> None:
    """The design decision worth pinning.

    A gate on settle/claim would TRAP FUNDS: a player who reached a duel and then
    failed an attestation check could not play, settle, or claim — their stake
    would sit in the escrow until the refund window. Gate the door, never the exit.
    """
    token = _sign_in(confirm=False)
    assert token is not None
    for path, body in (
        ("/api/round/commit", {"matchId": "a" * 32, "roundIndex": 0, "intentHash": "0x" + "ab" * 32}),
        ("/api/round/result", {"matchId": "a" * 32, "roundIndex": 0, "measuredMs": 250.0, "resultProof": ""}),
    ):
        status, payload = _api(path, body, token)
        detail = json.dumps(payload).lower()
        assert not (status == 403 and "eligibility" in detail), (
            f"{path} must not refuse for eligibility — that would strand funds: {status} {payload}"
        )


def test_the_status_endpoint_reports_the_truth() -> None:
    unattested = _sign_in(confirm=False)
    attested = _sign_in(confirm=True)
    assert unattested and attested
    status, body = _api("/api/eligibility", token=unattested)
    assert status == 200 and body.get("attested") is False, body
    status, body = _api("/api/eligibility", token=attested)
    assert status == 200 and body.get("attested") is True, body


def test_confirming_without_the_assertion_is_refused() -> None:
    token = _sign_in(confirm=False)
    assert token is not None
    status, body = _api("/api/eligibility/confirm", {"ageConfirmed": False}, token)
    assert status == 400, f"a false assertion must not be recorded: {status} {body}"
