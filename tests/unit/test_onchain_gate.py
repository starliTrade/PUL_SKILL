"""The on-chain deposit gate, driven by the reusable fake RPC (plan item 0.6).

Two jobs in one module:
  1. Prove `tests/fixtures/fake_rpc.py` can drive the REAL gate code end to end
     (the fixture's acceptance criterion for item 0.6).
  2. Pin the C2 red baseline (audit finding C2) so phase 1 has a failing test to
     fix: a transient RPC failure must not become a permanently sticky
     `_token_decimals = None`, and "cannot read" must not be treated as
     "does not match" (which voids the match and costs the winner the prize).
"""

from __future__ import annotations

import pytest

import match_engine as engine
import onchain
from tests.fixtures.fake_rpc import (
    SEL_DECIMALS,
    STATUS_ACTIVE,
    STATUS_CREATED,
    Duel,
    FakeRpc,
    configure_escrow,
)

P1 = "0x" + "11" * 20
P2 = "0x" + "22" * 20


def _match(match_id: str = "aa" * 16, stake: float = 1.0) -> engine.Match:
    m = engine.Match(match_id=match_id, stake=stake, created_at=0.0)
    m.players = {P1: {"address": P1, "joinedAt": 0.0}, P2: {"address": P2, "joinedAt": 0.0}}
    m.creator, m.joiner = P1, P2
    m.status = "active"
    m.activated_at = 0.0
    return m


@pytest.fixture
def rpc(monkeypatch):
    return configure_escrow(monkeypatch, FakeRpc(duel=Duel(status=STATUS_ACTIVE, player1=P1, player2=P2)))


# --- 1. the fixture drives the real gate --------------------------------------
def test_gate_is_inactive_without_escrow_config(monkeypatch):
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    monkeypatch.delenv("ESCROW_RPC_URL", raising=False)
    import main as server

    assert onchain.escrow_configured() is False
    assert server._verify_deposits_or_void(_match()) is None  # practice mode: gate off


def test_active_matching_duel_lets_the_round_proceed(rpc):
    import main as server

    assert server._verify_deposits_or_void(_match()) is None


def test_mismatched_stake_voids_the_match(rpc):
    import main as server

    rpc.duel.stake_units = 1  # dust stake while the UI promised 1.0 USDT
    m = _match()
    gate = server._verify_deposits_or_void(m)
    assert gate and gate.get("void") is True
    assert m.status == "void"


def test_mismatched_participants_void_the_match(rpc):
    import main as server

    rpc.duel.player2 = "0x" + "99" * 20  # deposited from a different wallet
    m = _match()
    gate = server._verify_deposits_or_void(m)
    assert gate and gate.get("void") is True


def test_dead_rpc_fails_closed_without_voiding(rpc):
    """An unreadable chain must refuse the round — never silently allow it."""
    import main as server
    from fastapi import HTTPException

    rpc.fail_next(10)
    m = _match()
    with pytest.raises(HTTPException) as exc:
        server._verify_deposits_or_void(m)
    assert exc.value.status_code == 409
    assert m.status == "active", "an unreadable RPC must not void the match"


def test_created_duel_past_the_deposit_timeout_voids(rpc):
    import main as server

    rpc.duel.status = STATUS_CREATED
    m = _match()
    m.activated_at = -10_000.0  # long past DEPOSIT_TIMEOUT_SECONDS
    gate = server._verify_deposits_or_void(m)
    assert gate and gate.get("void") is True


def test_chain_mismatch_fails_closed(rpc, monkeypatch):
    monkeypatch.setenv("ORACLE_CHAIN_ID", "137")  # RPC says 80002
    assert onchain.duel_status("aa" * 16) is None


def test_decimals_are_read_from_the_token(rpc):
    assert onchain.token_decimals() == 6


# --- 2. C2 red baseline -------------------------------------------------------
# Remove the xfail markers in the same commit as the phase-1 fix.
c2 = pytest.mark.xfail(strict=True, reason="audit C2 not fixed yet (phase 1)")


@c2
def test_transient_failure_does_not_stick(rpc):
    """One 5-second RPC blip must not poison the decimals cache forever.

    Audit C2: `_token_decimals` is set to None on ANY failure and the guard
    `if _token_decimals != "unread": return _token_decimals` then returns that
    None for the life of the process. Every subsequent ACTIVE duel fails
    `verify_deposit`, and `main._verify_deposits_or_void` turns that failure
    into `m.status = "void"` — so the legitimate winner is never paid.
    """
    rpc.fail_next(1)
    assert onchain.token_decimals() is None  # the blip

    # The RPC is healthy again; the cache must retry (negative TTL, like _chain_ok).
    assert onchain.token_decimals() == 6


@c2
def test_unreadable_decimals_refuses_the_round_without_voiding(rpc):
    """"Cannot read" is not "does not match" — it must not void the match.

    The injection is deliberately NARROW (`break_call(SEL_DECIMALS)`, not
    `return_malformed("eth_call")`): breaking every eth_call also breaks the
    duel read, so the gate would short-circuit at "duel unreadable" and this
    test would pass without ever reaching the decimals path — a false green.
    The two asserts below prove the duel really is readable first.
    """
    import main as server
    from fastapi import HTTPException

    rpc.break_call(SEL_DECIMALS)
    onchain._token_decimals = "unread"
    onchain._cache.clear()

    m = _match()

    # Precondition: the duel itself is perfectly readable and matching.
    info = onchain.duel_info(m.match_id)
    assert info is not None and info["status"] == STATUS_ACTIVE, "the duel read must stay healthy"
    assert onchain.token_decimals() is None, "decimals must be the only unreadable call"

    onchain._token_decimals = "unread"
    with pytest.raises(HTTPException) as exc:
        server._verify_deposits_or_void(m)
    assert exc.value.status_code == 409
    assert m.status == "active", "an unreadable token must not void the match (audit C2)"
