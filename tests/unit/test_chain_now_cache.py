"""The chain-clock cache must not be anchored to a clock that can be moved.

`onchain.chain_now()` is what `oracle.sign_settlement` uses to mint the
settlement deadline, so its staleness is a money-path property: a stale value
produces `deadline = stale + 600`, the contract compares it against the block
timestamp, and the proof arrives already expired. Settlement becomes impossible
and the winner is forced onto the refund path, which pays both players.

The first version of the cache stamped entries with `timebase.now()` — the
business clock tests and the time-travel drill move. A test that advanced the
clock two hours and then read the chain wrote a stamp two hours in the FUTURE;
after the clock was restored, `now - stamp` was negative and therefore "fresh"
for the next two real hours. That is not a test-only problem: an NTP step or an
operator time change does the same thing in production.

These tests pin the TTL to a monotonic clock, and they fail against the old
implementation for the reason described above.
"""
from __future__ import annotations

import pytest
import timebase

import onchain


@pytest.fixture(autouse=True)
def _clean_cache():
    onchain.reset_chain_now_cache()
    yield
    onchain.reset_chain_now_cache()


def _rpc_returning(value: int, calls: list[int]):
    def fake(method: str, params: list):
        assert method == "eth_getBlockByNumber"
        calls.append(value)
        return {"result": {"timestamp": hex(value)}}

    return fake


def test_the_first_read_hits_the_rpc_and_the_second_does_not(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_000, calls))
    assert onchain.chain_now() == 1_700_000_000
    assert onchain.chain_now() == 1_700_000_000
    assert calls == [1_700_000_000], "the 5 s cache did not deduplicate the read"


def test_the_entry_expires_on_a_monotonic_clock(monkeypatch) -> None:
    calls: list[int] = []
    clock = {"t": 1000.0}
    monkeypatch.setattr(onchain.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_000, calls))

    assert onchain.chain_now() == 1_700_000_000
    clock["t"] += 4.0  # inside the 5 s window
    assert onchain.chain_now() == 1_700_000_000
    assert len(calls) == 1

    clock["t"] += 2.0  # now past it
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_123, calls))
    assert onchain.chain_now() == 1_700_000_123
    assert len(calls) == 2, "an expired entry was served from the cache"


def test_jumping_the_business_clock_forward_does_not_freeze_the_cache(monkeypatch) -> None:
    """The regression that produced a red chain gate on 2026-10-24.

    With a `timebase.now()` stamp: advance the business clock by two hours, read
    the chain once, restore the clock, and every later read inside those two hours
    returns the OLD chain time. With a monotonic stamp the jump is irrelevant.
    """
    calls: list[int] = []
    real_now = timebase.now
    clock = {"t": 5000.0}
    monkeypatch.setattr(onchain.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_000, calls))

    # A time-travel test moves the business clock two hours forward and reads.
    monkeypatch.setattr(timebase, "now", lambda: real_now() + 7200)
    assert onchain.chain_now() == 1_700_000_000

    # The test ends; the clock is back. Real time has advanced 30 s.
    monkeypatch.setattr(timebase, "now", real_now)
    clock["t"] += 30.0
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_900, calls))
    assert onchain.chain_now() == 1_700_000_900, (
        "a forward jump of the business clock kept a stale chain time alive"
    )


def test_an_unreadable_chain_does_not_poison_the_cache(monkeypatch) -> None:
    """A failed read must not be cached as a value, and must not raise."""

    def boom(method: str, params: list):
        raise RuntimeError("rpc down")

    monkeypatch.setattr(onchain, "_rpc_call", boom)
    assert onchain.chain_now() is None
    calls: list[int] = []
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_000, calls))
    assert onchain.chain_now() == 1_700_000_000


def test_a_future_dated_block_is_returned_as_is(monkeypatch) -> None:
    """The function reports the CHAIN's time; it does not second-guess it.

    Clamping or "sanity-checking" a chain time that looks wrong would hide the
    very drift the caller is trying to escape.
    """
    calls: list[int] = []
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(2_000_000_000, calls))
    assert onchain.chain_now() == 2_000_000_000


def test_a_cached_value_never_crosses_an_endpoint_change(monkeypatch) -> None:
    """Two chains do not share a clock, so the URL is part of the cache key.

    `test_chain_now_returns_none_instead_of_raising_when_unreachable` had to call
    `reset_chain_now_cache()` by hand after pointing ESCROW_RPC_URL at a dead
    port, with a comment saying that otherwise it reads "the previous chain's
    value". A manual step like that is a bug waiting for the next caller.
    """
    calls: list[int] = []
    monkeypatch.setenv("ESCROW_RPC_URL", "http://127.0.0.1:8545")
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_700_000_000, calls))
    assert onchain.chain_now() == 1_700_000_000

    # A different chain, a different clock, well inside the 5 s window.
    monkeypatch.setenv("ESCROW_RPC_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(onchain, "_rpc_call", _rpc_returning(1_600_000_000, calls))
    assert onchain.chain_now() == 1_600_000_000, "the cache crossed an endpoint change"
