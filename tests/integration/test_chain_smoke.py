"""End-to-end money path on a real EVM (plan item 0.8).

Acceptance for 0.8: "a sample test runs createDuel on anvil and verifies the
balance." This module goes further on purpose — it also settles a duel with a
signature produced by the REAL `api/oracle.py`, because that is the only way to
prove the three-way contract (oracle digest ↔ onchain decoder ↔ Solidity) still
holds. A drift there is invisible to unit tests and only shows up as a revert
with real money locked in escrow.

Requires: scripts/start_anvil.sh --bg
"""

from __future__ import annotations

import hashlib
import os
import time

import pytest

import onchain
import oracle
from tests.fixtures.chain import ChainUnavailable, LocalChain, match_id_bytes

pytestmark = pytest.mark.chain

USDT = 10**6  # MockUSDT has 6 decimals


@pytest.fixture(scope="module")
def chain() -> LocalChain:
    try:
        c = LocalChain()
    except ChainUnavailable as exc:
        pytest.skip(str(exc))
    if not c.is_up():
        pytest.skip("anvil is not running — run scripts/start_anvil.sh --bg")
    return c


@pytest.fixture
def funded(chain: LocalChain):
    """Two players holding 100 MockUSDT each, with the escrow approved."""
    players = chain.manifest["players"]
    for p in players:
        chain.faucet(p["address"], 100 * USDT)
        chain.approve(p["privateKey"], chain.escrow, 100 * USDT)
    return players


def _fresh_id(tag: str) -> bytes:
    """A per-run unique match id.

    anvil keeps its state between runs, and `createDuel` reverts on an existing
    matchId — so a deterministic id would make the second run fail with
    "Match already exists" instead of testing anything.
    """
    salt = f"{tag}:{time.time_ns()}:{os.getpid()}"
    return hashlib.sha256(salt.encode()).digest()


# --- deployment sanity --------------------------------------------------------
def test_escrow_points_at_the_deployed_token_and_oracle(chain: LocalChain):
    assert chain.escrow_payment_token().lower() == chain.token.lower()
    assert chain.escrow_oracle_signer().lower() == chain.oracle.lower()


def test_match_id_convention_matches_the_server(chain: LocalChain):
    """The client/server/oracle id convention must not drift from the tests'."""
    raw = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    assert match_id_bytes(raw) == bytes.fromhex(onchain._match_id_to_bytes32(raw)[2:])
    assert match_id_bytes(raw) == oracle._match_id_bytes32(raw)


# --- the money path -----------------------------------------------------------
def test_create_duel_locks_the_stake(chain: LocalChain, funded):
    p1 = funded[0]
    mid = _fresh_id("create-duel")
    before = chain.balance_of(chain.escrow)

    chain.create_duel(p1["privateKey"], mid, 1 * USDT)

    state = chain.duel_state(mid)
    assert state.status_name == "Created"
    assert state.player1.lower() == p1["address"].lower()
    assert state.stake_amount == 1 * USDT
    assert chain.balance_of(chain.escrow) - before == 1 * USDT


def test_join_duel_activates_and_doubles_the_pool(chain: LocalChain, funded):
    p1, p2 = funded[0], funded[1]
    mid = _fresh_id("join-duel")
    chain.create_duel(p1["privateKey"], mid, 2 * USDT)
    chain.join_duel(p2["privateKey"], mid)

    state = chain.duel_state(mid)
    assert state.status_name == "Active"
    assert state.player2.lower() == p2["address"].lower()
    assert state.total_pool == 4 * USDT


def test_join_below_minimum_stake_reverts(chain: LocalChain, funded):
    p1 = funded[0]
    mid = _fresh_id("dust")
    with pytest.raises(RuntimeError, match="reverted"):
        chain.create_duel(p1["privateKey"], mid, 1)  # 1 base unit, below MIN_STAKE_UNITS


def test_settlement_with_a_real_oracle_signature_pays_the_winner(
    chain: LocalChain, funded, monkeypatch
):
    """R7: a signature from api/oracle.py must be accepted by the deployed contract.

    This is the test that would have caught every past digest drift (padded vs
    raw address, wrong chain id, wrong escrow binding, high-s rejection).
    """
    p1, p2 = funded[0], funded[1]
    mid = _fresh_id("settle")
    stake = 5 * USDT
    chain.create_duel(p1["privateKey"], mid, stake)
    chain.join_duel(p2["privateKey"], mid)

    # Point the oracle at THIS chain and THIS escrow.
    monkeypatch.setenv("ORACLE_CHAIN_ID", str(chain.chain_id))
    monkeypatch.setenv("ESCROW_ADDRESS", chain.escrow)
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", chain.manifest["oracleKey"])

    record = {
        "status": "settled",
        "matchId": "0x" + mid.hex(),
        "winner": p1["address"],
        "winnerTimeMs": 220,
        "loserTimeMs": 310,
        "validatedTimes": {p1["address"].lower(): [220.0], p2["address"].lower(): [310.0]},
    }
    envelope = oracle.sign_settlement(record, chain_id=chain.chain_id)
    assert envelope["oracleAddress"].lower() == chain.oracle.lower()

    winner_before = chain.balance_of(p1["address"])
    treasury_before = chain.balance_of(chain.treasury)

    chain.settle_duel(
        p1["privateKey"],
        mid,
        envelope["winner"],
        envelope["winnerTimeMs"],
        envelope["loserTimeMs"],
        envelope["serverNonce"],
        envelope["deadline"],
        bytes.fromhex(envelope["signature"].removeprefix("0x")),
    )

    state = chain.duel_state(mid)
    assert state.status_name == "Settled"
    assert state.winner.lower() == p1["address"].lower()

    platform_fee = (stake * 2 * 200) // 10_000
    assert chain.balance_of(p1["address"]) - winner_before == stake * 2 - platform_fee
    assert chain.balance_of(chain.treasury) - treasury_before == platform_fee


def test_settlement_from_a_foreign_signer_reverts(chain: LocalChain, funded, monkeypatch):
    """A signature that is not the contract's oracle must be rejected."""
    p1, p2 = funded[0], funded[1]
    mid = _fresh_id("forged-settle")
    chain.create_duel(p1["privateKey"], mid, 1 * USDT)
    chain.join_duel(p2["privateKey"], mid)

    monkeypatch.setenv("ORACLE_CHAIN_ID", str(chain.chain_id))
    monkeypatch.setenv("ESCROW_ADDRESS", chain.escrow)
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)  # not the contract's oracle

    record = {
        "status": "settled",
        "matchId": "0x" + mid.hex(),
        "winner": p1["address"],
        "winnerTimeMs": 200,
        "loserTimeMs": 300,
        "validatedTimes": {p1["address"].lower(): [200.0], p2["address"].lower(): [300.0]},
    }
    envelope = oracle.sign_settlement(record, chain_id=chain.chain_id)

    with pytest.raises(RuntimeError, match="reverted"):
        chain.settle_duel(
            p1["privateKey"],
            mid,
            envelope["winner"],
            envelope["winnerTimeMs"],
            envelope["loserTimeMs"],
            envelope["serverNonce"],
            envelope["deadline"],
            bytes.fromhex(envelope["signature"].removeprefix("0x")),
        )
