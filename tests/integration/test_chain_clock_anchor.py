"""The settlement deadline is anchored to the CHAIN's clock (plan item 11.1).

Found by a time-travel test and left open until now: `oracle.sign_settlement`
computed the deadline from `timebase.now()` — the SERVER's clock — while the
contract enforces `block.timestamp <= proof.deadline` on the CHAIN's.

A drift larger than the deadline window makes every proof arrive ALREADY EXPIRED.
Settlement becomes impossible, the winner cannot claim, and the only remaining
path is the refund — which pays BOTH players and takes the win away from the
player who earned it.

These tests pin the fix: the clock is read from the chain the contract will use.
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

# Marked `chain` so the chain gate SELECTS it. Audit 2026-10-16: without this
# marker the module was selected by no gate at all — the general pytest gate runs
# before anvil starts, and the `-m chain` gate did not include it. A test that
# never runs is not coverage, and this one pins the money-path clock anchor.
pytestmark = pytest.mark.chain

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(ROOT, "contracts", "deployments", "local.json")


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
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.load(res)


@pytest.fixture(autouse=True)
def _chain_env(monkeypatch: pytest.MonkeyPatch):
    m = _manifest()
    monkeypatch.setenv("ESCROW_RPC_URL", m["rpcUrl"])
    monkeypatch.setenv("ESCROW_ADDRESS", m["escrow"])
    monkeypatch.setenv("ORACLE_CHAIN_ID", str(m["chainId"]))
    monkeypatch.setenv("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", m["oracleKey"])
    # The chain must actually be up for any of this to mean anything.
    try:
        _rpc(m["rpcUrl"], "eth_chainId", [])
    except Exception:  # noqa: BLE001
        pytest.skip("anvil is not running — run scripts/start_anvil.sh --bg")


def test_chain_now_reads_the_chain() -> None:
    """The helper the deadline depends on must return the CHAIN's time."""
    import onchain

    m = _manifest()
    expected = int(
        _rpc(m["rpcUrl"], "eth_getBlockByNumber", ["latest", False])["result"]["timestamp"], 16
    )
    got = onchain.chain_now()
    assert got is not None, "chain_now must read a live chain"
    # Anvil mines on demand, so the block may advance between the two reads.
    assert abs(got - expected) <= 60, f"chain_now={got} is not the chain's time ({expected})"


def test_chain_now_returns_none_instead_of_raising_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead RPC must not crash the signing path — it degrades to the local clock."""
    import onchain

    monkeypatch.setenv("ESCROW_RPC_URL", "http://127.0.0.1:9")
    # The clock is CACHED for a few seconds (a fix for blocking I/O inside the
    # store transaction), so a test that changes the RPC must forget it first —
    # otherwise it reads the previous chain's value and the assertion is about
    # the cache, not about the dead endpoint.
    onchain.reset_chain_now_cache()
    assert onchain.chain_now() is None


def test_the_deadline_is_inside_the_chain_window() -> None:
    """The property the contract enforces, asserted against the chain itself.

    `block.timestamp <= proof.deadline` — so the deadline must be in the chain's
    future, not merely in the server's.
    """
    import match_engine
    import onchain
    import oracle

    m = _manifest()
    chain_now = onchain.chain_now()
    assert chain_now is not None

    record = {
        "status": "settled",
        "matchId": "0x" + "ab" * 32,
        "winner": m["players"][0]["address"],
        "winnerTimeMs": 220,
        "loserTimeMs": 310,
        "validatedTimes": {
            m["players"][0]["address"].lower(): [220.0],
            m["players"][1]["address"].lower(): [310.0],
        },
    }
    match_engine.stamp_settlement(record)
    envelope = oracle.sign_settlement(record, chain_id=m["chainId"])

    deadline = int(envelope["deadline"])
    assert deadline > chain_now, (
        f"the deadline ({deadline}) must be in the CHAIN's future ({chain_now}) — "
        "otherwise the contract rejects every proof as expired"
    )
    # And it must not outlive the window it claims to be valid for.
    assert deadline <= chain_now + oracle.SETTLEMENT_DEADLINE_SECONDS + 5


def test_the_horizon_mirrors_the_contracts_clock_origin() -> None:
    """The contract's origin is max(activatedAt, createdAt) — NOT activatedAt.

        uint256 clockOrigin = activatedAt[proof.matchId] > duel.createdAt
            ? activatedAt[proof.matchId]
            : duel.createdAt;

    Audit 2026-10-16: the first version of the chain-anchoring fix read
    `activatedAt` alone. A duel deposited long before it paired has
    `createdAt > activatedAt`, so that horizon was SHORTER than the contract's —
    and a valid settlement would be refused, leaving the winner unable to claim.
    Found by reading the contract's own expression instead of assuming it.

    This asserts both halves are readable, which is what the mirror needs.
    """
    import hashlib

    import onchain

    m = _manifest()
    # A duel id the escrow has never seen: both reads must return None rather
    # than raising, because the caller treats None as "no chain opinion".
    unknown = hashlib.sha256(b"never-created").hexdigest()[:32]
    assert onchain.duel_activated_at(unknown) in (None, 0)

    # `duel_created_at` is deliberately NOT read: the contract's origin is
    # `max(activatedAt, createdAt)`, and `joinDuel` sets `activatedAt` strictly
    # after `createDuel` set `createdAt` (PulsarEscrow.sol:337, 367) — so the max
    # is always `activatedAt`. Reading it cost a second eth_call inside the store
    # transaction for a branch that cannot occur.
    assert not hasattr(onchain, "duel_created_at"), (
        "the redundant createdAt read must not come back without a reason"
    )
    assert m["escrow"], "the manifest must name an escrow"
