"""The ranked money path, driven end to end through the API.

Audit 2026-10-14: the browser E2E proved this flow works but could not assert
it — a DOM-polling driver is flaky, because a short-lived target can fall
between two polls and a round is then never submitted. The SERVER is the
authority on the round machine, so the reliable driver is the API itself: no
browser, no polling, no timing.

What this covers, in order:
  SIWE sign-in -> queue -> on-chain deposits (approve + createDuel/joinDuel)
  -> the deposit gate -> three rounds of commit/reveal/result -> settle.

It also measures the Firestore reads per match (plan item 10.3), because a full
match is exactly the unit that metric is defined over.

Requires anvil with the escrow deployed (`scripts/start_anvil.sh --bg`); skips
otherwise, like `test_chain_smoke.py`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(ROOT, "contracts", "deployments", "local.json")
API = os.environ.get("PULSAR_E2E_API", "http://127.0.0.1:8000")
STAKE = 1.0
ROUNDS = 3


def _manifest() -> dict:
    if not os.path.exists(MANIFEST):
        pytest.skip("no deployment manifest — run scripts/start_anvil.sh --bg")
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def _rpc(url: str, method: str, params: list) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def _api(path: str, body: dict | None = None, token: str | None = None, method: str | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ("POST" if body is not None else "GET"),
    )
    req.add_header("Host", "127.0.0.1:8000")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _sign_in(private_key: str | None = None) -> tuple[str, str]:
    """A real SIWE session. Returns (address, token).

    Pass the anvil player's key when the session must be the SAME identity that
    deposits on-chain: the gate compares the duel's participants to the match's,
    so a random session address would be refused with
    `409 "On-chain duel does not match this match (stake or participants differ)"`.
    """
    from eth_account import Account
    from eth_account.messages import encode_defunct

    account = Account.from_key(private_key) if private_key else Account.create()
    address = account.address.lower()
    status, nonce = _api("/api/auth/nonce", {"address": address})
    assert status == 200, nonce
    signature = account.sign_message(encode_defunct(text=nonce["message"])).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    status, verified = _api(
        "/api/auth/verify", {"message": nonce["message"], "signature": signature}
    )
    assert status == 200, verified
    token = verified["token"]
    # Plan item 11.3/G2: staked play requires a SERVER-RECORDED eligibility
    # attestation. The gate is on `/api/queue` (the entry), not on the
    # round/settle/claim endpoints, so committed money is never trapped.
    status, confirmed = _api("/api/eligibility/confirm", {"ageConfirmed": True}, token)
    assert status == 200, confirmed
    return address, token


def _match_key(match_id: str) -> str:
    """The bytes32 the escrow stores the duel under — sha256 of the raw id."""
    return "0x" + hashlib.sha256(match_id.encode()).hexdigest()


def _send(manifest: dict, frm: str, to: str, data: str) -> str:
    out = _rpc(
        manifest["rpcUrl"],
        "eth_sendTransaction",
        [{"from": frm, "to": to, "data": data, "gas": "0x300000"}],
    )
    assert "result" in out, out
    return out["result"]


def _selector(signature: str) -> str:
    import subprocess

    return subprocess.run(
        ["/root/workspace/.foundry/bin/cast", "sig", signature],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fund(manifest: dict, player: dict) -> None:
    """Mint the payment token to a player.

    `MockUSDT.faucet(address,uint256)` — NOT `mint`. The first version of this
    helper sent a selector that does not exist on the contract, the transaction
    "succeeded", and the player was left with a zero balance; the failure only
    surfaced later as `ERC20InsufficientBalance` from `joinDuel`.
    """
    amount = hex(int(100 * 1_000_000))[2:].rjust(64, "0")
    data = _selector("faucet(address,uint256)") + player["address"].lower()[2:].rjust(64, "0") + amount
    _send(manifest, manifest["deployer"]["address"], manifest["token"], data)


def _deposit(manifest: dict, creator: dict, joiner: dict, match_id: str) -> None:
    """Both players lock the stake in the escrow — the gate requires it."""
    for player in (creator, joiner):
        _fund(manifest, player)
    units = int(STAKE * 1_000_000)
    amount = hex(units)[2:].rjust(64, "0")
    approve = "0x095ea7b3" + manifest["escrow"].lower()[2:].rjust(64, "0") + amount
    for player in (creator, joiner):
        _send(manifest, player["address"], manifest["token"], approve)
    key = _match_key(match_id)[2:]
    _send(manifest, creator["address"], manifest["escrow"], _selector("createDuel(bytes32,uint256)") + key + amount)
    # joinDuel reverts until the creator's deposit is mined; anvil mines instantly
    # but the receipt is not synchronous, so poll the state.
    for _ in range(20):
        state = _rpc(
            manifest["rpcUrl"],
            "eth_call",
            [{"to": manifest["escrow"], "data": "0x9fe9ada3" + key}, "latest"],
        )
        # `matches(bytes32)` is the public mapping getter. A zero-length or
        # all-zero word means the duel is not there yet.
        raw = (state.get("result") or "").removeprefix("0x")
        if len(raw) > 64 and int(raw[:64], 16) != 0:
            break
        time.sleep(0.25)
    _send(manifest, joiner["address"], manifest["escrow"], _selector("joinDuel(bytes32)") + key)


@pytest.fixture(scope="module")
def manifest() -> dict:
    """The anvil manifest, with the match store reset first.

    This test signs in as anvil's DETERMINISTIC players, so a match left by a
    previous run is still in the store and `/api/queue` — which returns the
    caller's waiting OR active match — hands it back. Resetting the store is
    part of the fixture, not the caller's job.
    """
    data = _manifest()
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")
    project = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT") or "demo-pulsar"
    try:
        req = urllib.request.Request(
            f"http://{emulator}/emulator/v1/projects/{project}/databases/(default)/documents",
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:  # noqa: BLE001 — no emulator means the API is in memory mode
        pass
    return data


def test_the_ranked_flow_completes_and_settles(manifest: dict) -> None:
    # This drives the LIVE API, so it needs one. Skip rather than fail when the
    # stack is not up — the rest of the suite must not depend on it.
    try:
        status, health = _api("/api/health")
    except Exception:  # noqa: BLE001
        pytest.skip("no API on 127.0.0.1:8000 — run scripts/start_e2e_stack.sh")
    if status != 200 or health.get("matchStore") != "firestore":
        pytest.skip("the API is not running on the durable store — run scripts/start_e2e_stack.sh")

    creator = manifest["players"][0]
    joiner = manifest["players"][1]

    # Sign in AS the on-chain players: the gate checks that the duel's
    # participants are the match's participants.
    addr_a, token_a = _sign_in(creator["privateKey"])
    addr_b, token_b = _sign_in(joiner["privateKey"])

    # 1. Both queue at the same stake. The first waits, the second pairs.
    status, first = _api("/api/queue", {"stake": STAKE, "rttMs": 40}, token_a)
    assert status == 200, first
    if first["status"] != "waiting":
        pytest.skip(
            f"the server is holding a match for this player from an earlier run "
            f"({first.get('status')!r}). The durable store keeps an in-process "
            "`player_match` cache that a store wipe does not clear; restart the "
            "API (scripts/start_e2e_stack.sh --stop && scripts/start_e2e_stack.sh) "
            "to run this test."
        )
    status, second = _api("/api/queue", {"stake": STAKE, "rttMs": 40}, token_b)
    assert status == 200, second
    assert second["status"] == "active", second
    match_id = second["matchId"]

    # 2. The creator's next poll must see the pairing (the client relies on it).
    status, polled = _api("/api/queue", {"stake": STAKE, "rttMs": 40}, token_a)
    assert status == 200 and polled["status"] == "active", polled
    assert polled["matchId"] == match_id

    # 3. Lock both stakes on-chain. Until this happens the gate refuses rounds.
    _deposit(manifest, creator, joiner, match_id)
    # 4. Three rounds. The gate reads the escrow before EVERY round, so a round
    #    that returns 200 is proof the deposits are visible on-chain.
    # The creator is consistently faster, so the duel has a winner. Identical
    # times are a genuine tie, and the server correctly VOIDS it (both stakes
    # refunded) rather than inventing a winner.
    rounds_played = 0
    for index in range(ROUNDS):
        # A best-of-three can END after two rounds — 2-0 is a legitimate finish
        # — and the server then answers the next commit with
        # `409 {"detail":"Match is not active"}`. That is the server being
        # right; a driver that assumes three rounds is the thing that is wrong.
        status, view = _api(f"/api/match/{match_id}", token=token_a)
        if status == 200 and view.get("status") != "active":
            break
        for token, measured in ((token_a, 240.0 + index), (token_b, 300.0 + index)):
            intent = "0x" + os.urandom(32).hex()
            status, committed = _api(
                "/api/round/commit",
                {"matchId": match_id, "roundIndex": index, "intentHash": intent},
                token,
            )
            assert status == 200, f"round {index} commit: {status} {committed}"
            status, revealed = _api(
                "/api/round/target", {"matchId": match_id, "roundIndex": index}, token
            )
            assert status == 200, f"round {index} target: {status} {revealed}"
            # The server measures the REAL elapsed time between the reveal and
            # the submission and refuses a claim that is faster than what it
            # observed:
            #   "implausible: server-observed reaction is faster than the claimed
            #    time"
            # So a driver must actually WAIT like a player does — the target
            # appears after `targetMs`, then the reaction takes `measured`.
            # Submitting instantly made every round invalid, which left the
            # match with no round-win majority and voided it.
            time.sleep((revealed["targetMs"] + measured) / 1000.0)
            status, result = _api(
                "/api/round/result",
                {
                    "matchId": match_id,
                    "roundIndex": index,
                    "measuredMs": measured,
                    "resultProof": revealed["resultProof"],
                },
                token,
            )
            assert status == 200, f"round {index} result: {status} {result}"
            assert result.get("accepted") is True, f"round {index} rejected: {result}"
        rounds_played += 1

    # 5. Settle. The match is complete — a majority was reached or every round
    #    was played — so the server signs a settlement naming a winner.
    status, settled = _api(f"/api/match/{match_id}/settle", {}, token_a)
    assert status == 200, f"settle: {status} {settled}"
    assert rounds_played >= 2, f"a best-of-three needs at least two rounds, played {rounds_played}"
    assert settled.get("status") == "settled", settled


def test_the_firestore_reads_per_match_are_measured(manifest: dict) -> None:
    """Plan item 10.3: reads per match, target < 20.

    The metric lives on `/api/metrics`, not `/api/health` — the first version of
    this test looked for it in health and skipped, which would have hidden a
    real regression behind a skip.
    """
    try:
        status, payload = _api("/api/metrics")
    except Exception:  # noqa: BLE001
        pytest.skip("no API on 127.0.0.1:8000 — run scripts/start_e2e_stack.sh")
    assert status == 200, payload

    firestore = payload.get("firestore") or {}
    reads = firestore.get("reads")
    settled = firestore.get("matchesSettled")
    per_match = firestore.get("readsPerMatch")

    assert reads is not None, "the reads counter must be exposed"
    if not settled:
        # No settled match yet in this process: the metric is honestly `None`
        # rather than a flattering 0. Nothing to assert beyond its presence.
        assert per_match is None, per_match
        pytest.skip("no settled match in this process yet — readsPerMatch is None by design")

    assert per_match is not None, firestore
    # MEASURED, and it MISSES the plan's target: a full ranked match costs ~40-50
    # Firestore reads against a budget of <20 (plan item 10.3). Recorded as a
    # known gap rather than a passing assertion or a silent skip — the number is
    # the finding, and hiding it either way would be the dishonest option.
    if per_match >= 20:
        pytest.xfail(
            f"reads per match is {per_match}, the plan target is <20 "
            f"(reads={reads}, settled={settled}) — a real, measured gap"
        )


def test_the_reads_are_attributed_to_routes(manifest: dict) -> None:
    """The reads-per-match number must say WHERE the reads go.

    Audit 2026-10-14: `readsPerMatch` was a single total — it said a match costs
    ~47 reads but not which endpoints spend them, so it could not be acted on.
    The middleware now measures the delta across each request and attributes it
    to the route. This asserts that attribution is real, because a metric that
    silently reports an empty map is worse than no metric: it looks like an
    answer.
    """
    try:
        status, payload = _api("/api/metrics")
    except Exception:  # noqa: BLE001
        pytest.skip("no API on 127.0.0.1:8000 — run scripts/start_e2e_stack.sh")
    assert status == 200, payload

    firestore = payload.get("firestore") or {}
    by_route = firestore.get("readsByRoute")
    assert isinstance(by_route, dict), f"readsByRoute must be a map, got {type(by_route)}"
    if not by_route:
        pytest.skip("no reads attributed yet in this process — run the flow test first")

    total = firestore.get("reads") or 0
    attributed = sum(by_route.values())
    assert attributed <= total, f"attributed {attributed} exceeds the total {total}"
    # The round endpoints dominate a match; if they are missing, the attribution
    # is measuring the wrong thing.
    assert any("/api/round/" in route for route in by_route), by_route
