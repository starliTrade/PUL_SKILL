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


def test_mismatched_stake_is_reported_as_a_void(rpc):
    """The gate is PURE (audit H10): it reports, the caller persists.

    It used to set `m.status = "void"` itself, which only worked because it ran
    inside the store transaction. Now that it runs outside the lock it must not
    mutate, so the void is persisted explicitly by `_gate_or_void`.
    """
    import main as server

    rpc.duel.stake_units = 1  # dust stake while the UI promised 1.0 USDT
    m = _match()
    gate = server._verify_deposits_or_void(m)
    assert gate and gate.get("void") is True
    assert m.status == "active", "the gate must not mutate the match any more"


def test_gate_or_void_persists_the_void(rpc, monkeypatch):
    """`_gate_or_void` refuses the round AND persists the void decision."""
    import main as server
    from fastapi import HTTPException

    # Force the in-memory backend: with FIRESTORE_EMULATOR_HOST set the server
    # boots Firestore-backed and this match only exists in process memory.
    monkeypatch.setattr(server.store, "_fs_store", None)
    server.store.memory.matches.clear()

    rpc.duel.stake_units = 1
    m = _match()
    server.store.memory.put(m)

    with pytest.raises(HTTPException) as exc:
        server._gate_or_void(m.match_id)
    assert exc.value.status_code == 409
    assert server.store.get(m.match_id).status == "void"


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


# --- 2. C2 regression suite (fixed in phase 1) --------------------------------
def test_transient_failure_does_not_stick(rpc, clock):
    """One 5-second RPC blip must not poison the decimals cache forever.

    Audit C2: `_token_decimals` was set to None on ANY failure and the guard
    `if _token_decimals != "unread": return _token_decimals` then returned that
    None for the life of the process. Every subsequent ACTIVE duel failed
    `verify_deposit`, and `main._verify_deposits_or_void` turned that failure
    into `m.status = "void"` — so the legitimate winner was never paid.

    A failure is now cached only for `_TOKEN_DECIMALS_RETRY_SECONDS` (so an
    outage does not hammer the RPC on every round action), then retried.
    """
    rpc.fail_next(1)
    assert onchain.token_decimals() is None  # the blip

    # Still inside the failure cache: no retry, no RPC hammering.
    assert onchain.token_decimals() is None
    assert rpc.calls_to("eth_call") <= 1

    clock.advance(onchain._TOKEN_DECIMALS_RETRY_SECONDS + 1)

    # The RPC is healthy again; the cache must retry and recover.
    assert onchain.token_decimals() == 6


def test_successful_read_is_cached_for_the_process(rpc):
    """decimals are immutable — a success must never be re-read."""
    assert onchain.token_decimals() == 6
    before = rpc.calls_to("eth_call")
    for _ in range(5):
        assert onchain.token_decimals() == 6
    assert rpc.calls_to("eth_call") == before, "a successful read was repeated"


def test_unreadable_decimals_refuses_the_round_without_voiding(rpc):
    """"Cannot read" is not "does not match" — it must not void the match.

    The injection is deliberately NARROW (`break_call(SEL_DECIMALS)`, not
    `return_malformed("eth_call")`): breaking every eth_call also breaks the
    duel read, so the gate would short-circuit at "duel unreadable" and this
    test would pass without ever reaching the decimals path — a false green.
    The asserts below prove the duel really is readable first.
    """
    import main as server
    from fastapi import HTTPException

    _unreadable_decimals(rpc)
    onchain._cache.clear()

    m = _match()

    # Precondition: the duel itself is perfectly readable and matching.
    info = onchain.duel_info(m.match_id)
    assert info is not None and info["status"] == STATUS_ACTIVE, "the duel read must stay healthy"
    assert onchain.token_decimals() is None, "decimals must be the only unreadable call"

    _unreadable_decimals(rpc)
    with pytest.raises(HTTPException) as exc:
        server._verify_deposits_or_void(m)
    assert exc.value.status_code == 409
    assert m.status == "active", "an unreadable token must not void the match (audit C2)"


def _unreadable_decimals(rpc) -> None:
    """Make ONLY decimals() unreadable, with a clean failure cache."""
    rpc.break_call(SEL_DECIMALS)
    onchain._token_decimals = "unread"
    onchain._token_decimals_retry_after = 0.0


def test_verdict_distinguishes_unknown_from_mismatch(rpc):
    """The three-way verdict is the mechanism that keeps C2 fixed."""
    duel = {"status": STATUS_ACTIVE, "player1": P1, "player2": P2, "stakeAmount": 1_000_000}

    assert onchain.deposit_verdict(duel, 1.0, [P1, P2], decimals=6) is onchain.DepositVerdict.MATCH
    assert (
        onchain.deposit_verdict(duel, 2.0, [P1, P2], decimals=6)
        is onchain.DepositVerdict.MISMATCH
    )
    assert (
        onchain.deposit_verdict(None, 1.0, [P1, P2], decimals=6) is onchain.DepositVerdict.UNKNOWN
    )
    # A readable but non-Active duel is a genuine mismatch, not "unknown".
    assert (
        onchain.deposit_verdict({**duel, "status": STATUS_CREATED}, 1.0, [P1, P2], decimals=6)
        is onchain.DepositVerdict.MISMATCH
    )
    # An unreadable token is UNKNOWN — the whole point of the three-way split.
    _unreadable_decimals(rpc)
    assert onchain.deposit_verdict(duel, 1.0, [P1, P2]) is onchain.DepositVerdict.UNKNOWN


def test_boolean_view_stays_fail_closed(rpc):
    """The legacy bool API must not start returning True for UNKNOWN."""
    duel = {"status": STATUS_ACTIVE, "player1": P1, "player2": P2, "stakeAmount": 1_000_000}
    assert onchain.verify_deposit(duel, 1.0, [P1, P2], decimals=6) is True
    assert onchain.verify_deposit(None, 1.0, [P1, P2], decimals=6) is False
    _unreadable_decimals(rpc)
    assert onchain.verify_deposit(duel, 1.0, [P1, P2]) is False


def test_absurd_decimals_are_rejected_not_crashed(rpc):
    """A token whose decimals() is garbage must fail CLOSED, not 500.

    Found while writing the C2 tests: `token_decimals()` accepted any 32-byte
    word, so a broken/hostile token returning 0xdeadbeef (3735928559) made
    `deposit_verdict` evaluate `Decimal(10) ** 3735928559` and raise
    decimal.Overflow — an unhandled 500 on the money path. ERC-20 decimals is
    a uint8, so anything above 255 is treated as an unreadable token.
    """
    import main as server
    from fastapi import HTTPException

    rpc.token_decimals = 3735928559  # 0xdeadbeef, a parseable but absurd word
    onchain._token_decimals = "unread"
    onchain._token_decimals_retry_after = 0.0
    onchain._cache.clear()

    assert onchain.token_decimals() is None, "an out-of-range decimals must read as unreadable"

    duel = {"status": STATUS_ACTIVE, "player1": P1, "player2": P2, "stakeAmount": 1_000_000}
    assert onchain.deposit_verdict(duel, 1.0, [P1, P2]) is onchain.DepositVerdict.UNKNOWN

    m = _match()
    with pytest.raises(HTTPException) as exc:
        server._verify_deposits_or_void(m)
    assert exc.value.status_code == 409, "must refuse the round, never crash or void"
    assert m.status == "active"
