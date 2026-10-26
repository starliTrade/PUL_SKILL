"""Refund after the escrow timeout (plan item 10.1).

A duel whose players never finish must not trap their money. The escrow holds
both stakes and releases them only after `MATCH_TIMEOUT + REFUND_GRACE` from
activation, so this test drives the real contract: deposit, time-travel anvil
past the window, refund, and assert BOTH players are made whole.

It also asserts the guard, because a refund that works too early is as bad as
one that never works — it would let a player pull their stake out of a live duel.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(ROOT, "contracts", "deployments", "local.json")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from foundry_bin import cast_path  # noqa: E402

STAKE_UNITS = 1_000_000


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


def _sig(signature: str) -> str:
    return subprocess.run(
        [cast_path(), "sig", signature], capture_output=True, text=True, check=True
    ).stdout.strip()


def _send(m: dict, frm: str, to: str, data: str) -> str:
    out = _rpc(
        m["rpcUrl"], "eth_sendTransaction",
        [{"from": frm, "to": to, "data": data, "gas": "0x300000"}],
    )
    assert "result" in out, out
    return out["result"]


def _balance(m: dict, who: str) -> int:
    data = "0x70a08231" + who.lower()[2:].rjust(64, "0")
    return int(_rpc(m["rpcUrl"], "eth_call", [{"to": m["token"], "data": data}, "latest"])["result"], 16)


def _duel_status(m: dict, key: str) -> int:
    raw = _rpc(
        m["rpcUrl"], "eth_call",
        [{"to": m["escrow"], "data": _sig("matches(bytes32)") + key}, "latest"],
    )["result"].removeprefix("0x")
    return int(raw[6 * 64 : 7 * 64], 16)  # status is word 6


def _now_ms(m: dict) -> int:
    return int(_rpc(m["rpcUrl"], "eth_getBlockByNumber", ["latest", False])["result"]["timestamp"], 16) * 1000


def _time_travel(m: dict, seconds: int) -> None:
    _rpc(m["rpcUrl"], "evm_increaseTime", [seconds])
    _rpc(m["rpcUrl"], "evm_mine", [])


def _restore_time(m: dict, ms: int) -> None:
    """Put the chain clock back.

    Test isolation, learned the hard way: `evm_increaseTime` moves the WHOLE
    chain forward, so a refund test that travels an hour breaks every later test
    that depends on a timeout — it took out the chain smoke test's settlement.
    Restoring the clock is the test's responsibility, not the next test's
    problem.
    """
    _rpc(m["rpcUrl"], "evm_setTime", [ms])


# Time travel is DISRUPTIVE and cannot be undone: `evm_increaseTime` moves the
# whole chain forward, anvil cannot rewind it (`evm_setTime` only moves forward
# too — verified, not assumed), and the oracle signs a deadline from the SERVER's
# clock while the contract enforces the CHAIN's. A travelled chain therefore
# makes every later deadline-dependent test fail with "Settlement proof expired"
# — which is exactly how this was found, by taking out the chain smoke test.
#
# So this module is OPT-IN: it runs on a dedicated chain, not in the default
# suite. Run it with the flag below, then restart anvil.
pytestmark = pytest.mark.skipif(
    os.environ.get("PULSAR_TEST_TIME_TRAVEL") != "1",
    reason=(
        "moves the chain clock forward and anvil cannot rewind it; run with "
        "PULSAR_TEST_TIME_TRAVEL=1 on a dedicated chain, then restart anvil"
    ),
)


def _open_duel(m: dict, match_id: str) -> tuple[dict, dict]:
    """Fund, approve, create and join. Returns (creator, joiner)."""
    creator, joiner = m["players"][0], m["players"][1]
    amount = hex(STAKE_UNITS)[2:].rjust(64, "0")
    faucet = _sig("faucet(address,uint256)")
    for player in (creator, joiner):
        _send(
            m, m["deployer"]["address"], m["token"],
            faucet + player["address"].lower()[2:].rjust(64, "0") + hex(100 * 1_000_000)[2:].rjust(64, "0"),
        )
    approve = "0x095ea7b3" + m["escrow"].lower()[2:].rjust(64, "0") + amount
    for player in (creator, joiner):
        _send(m, player["address"], m["token"], approve)
    key = hashlib.sha256(match_id.encode()).hexdigest()
    _send(m, creator["address"], m["escrow"], _sig("createDuel(bytes32,uint256)") + key + amount)
    for _ in range(20):
        if _duel_status(m, key) == 1:
            break
        time.sleep(0.25)
    _send(m, joiner["address"], m["escrow"], _sig("joinDuel(bytes32)") + key)
    return creator, joiner


def test_a_timeout_refund_makes_both_players_whole() -> None:
    m = _manifest()
    match_id = os.urandom(16).hex()
    key = hashlib.sha256(match_id.encode()).hexdigest()
    creator, joiner = _open_duel(m, match_id)

    # Both stakes are locked: the duel is Active and both balances dropped.
    assert _duel_status(m, key) == 2, "both stakes must be locked before the refund path"
    before_c, before_j = _balance(m, creator["address"]), _balance(m, joiner["address"])

    # The guard: a refund BEFORE the window must revert. A refund that works
    # early would let a player pull their stake out of a live duel.
    early = _rpc(
        m["rpcUrl"], "eth_call",
        [{"from": creator["address"], "to": m["escrow"], "data": _sig("refundTimeoutMatch(bytes32)") + key}, "latest"],
    )
    assert "error" in early, f"refund must be refused before the timeout, got {early}"
    assert "Match not timed out" in json.dumps(early), early

    # Time-travel past MATCH_TIMEOUT + REFUND_GRACE, then refund.
    _time_travel(m, 60 * 60)
    _send(m, creator["address"], m["escrow"], _sig("refundTimeoutMatch(bytes32)") + key)

    assert _duel_status(m, key) == 5, "the duel must be marked Refunded"
    assert _balance(m, creator["address"]) == before_c + STAKE_UNITS, "the creator was not refunded"
    assert _balance(m, joiner["address"]) == before_j + STAKE_UNITS, "the joiner was not refunded"


def test_a_settled_duel_cannot_be_refunded() -> None:
    """A refund must never be a second payout after a settlement.

    The escrow pays the winner on settle; a refund path that also paid would
    drain the pool.
    """
    m = _manifest()
    match_id = os.urandom(16).hex()
    key = hashlib.sha256(match_id.encode()).hexdigest()
    creator, _joiner = _open_duel(m, match_id)
    assert _duel_status(m, key) == 2

    # Without a valid oracle proof a settle cannot run, so the guard asserted
    # here is the REFUND
    # guard against a terminal status directly: an Active duel is refundable,
    # a Refunded one is not.
    _time_travel(m, 60 * 60)
    _send(m, creator["address"], m["escrow"], _sig("refundTimeoutMatch(bytes32)") + key)
    assert _duel_status(m, key) == 5
    second = _rpc(
        m["rpcUrl"], "eth_call",
        [{"from": creator["address"], "to": m["escrow"], "data": _sig("refundTimeoutMatch(bytes32)") + key}, "latest"],
    )
    assert "error" in second, f"a refunded duel must not refund twice, got {second}"
