"""
Phase 7 / M6 + M7 + M8 — the oracle.

**M6.** `_signature_to_low_s_bytes` normalises `s` but never validates `v`. A `v`
of 0/1 (the raw recovery id rather than the EIP-155 offset) or any other byte
passes straight through, and the resulting signature is then handed to the
contract. The contract rejects a `v` that is not 27/28, so the failure surfaces
as an on-chain revert AFTER a settlement was announced — the worst place to find
it.

**M7.** `sign_settlement` checks `status`, `winner` and `validatedTimes`, which
proves the record LOOKS like engine output. It cannot prove it IS engine output:
any caller that can build a dict with those keys gets a signature over real
money. The engine should stamp its records, and the oracle should require the
stamp.

**M8.** `_load_signer()` runs on every signature — `Account.from_key` performs an
EC scalar multiplication, which is the expensive part of signing. On the
settlement path this is pure waste.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from eth_account import Account  # noqa: E402

import oracle  # noqa: E402


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(oracle._KMS_KEY_ENV, "0x" + "11" * 32)
    oracle.reset_signer_cache()
    yield
    oracle.reset_signer_cache()


# --- M6: v must be 27 or 28 ---------------------------------------------------
def test_a_raw_recovery_id_is_rejected():
    """v=0/1 is the raw recovery id, not the EIP-155 offset."""
    raw = bytes(32) + bytes(32) + bytes([0])

    with pytest.raises(ValueError, match="v"):
        oracle._signature_to_low_s_bytes(raw)


def test_an_out_of_range_v_is_rejected():
    raw = bytes(32) + bytes(32) + bytes([99])

    with pytest.raises(ValueError, match="v"):
        oracle._signature_to_low_s_bytes(raw)


def test_both_valid_v_values_are_accepted():
    for v in (27, 28):
        raw = bytes(32) + bytes(32) + bytes([v])
        out = oracle._signature_to_low_s_bytes(raw)
        assert out[64] == v


def test_high_s_flips_v_between_the_valid_pair():
    """The normalisation must keep v inside {27, 28}."""
    high_s = (oracle._SECP256K1_N - 1).to_bytes(32, "big")
    raw = bytes(32) + high_s + bytes([27])

    out = oracle._signature_to_low_s_bytes(raw)

    assert out[64] in (27, 28), f"normalisation produced v={out[64]}"


# --- M7: the engine stamps its records ----------------------------------------
def _settled_record() -> dict:
    return {
        "status": "settled",
        "matchId": "a" * 32,
        "winner": "0x" + "11" * 20,
        "loser": "0x" + "22" * 20,
        "stake": 1.0,
        "roundWins": {"0x" + "11" * 20: 2, "0x" + "22" * 20: 0},
        "forfeits": {},
        "validatedTimes": {"0x" + "11" * 20: [220.0], "0x" + "22" * 20: [400.0]},
        "winnerTimeMs": 220,
        "loserTimeMs": 400,
    }


def test_an_unstamped_record_is_refused():
    """A dict that merely LOOKS like engine output must not be signed."""
    record = _settled_record()  # no engine stamp

    with pytest.raises(ValueError, match="engine"):
        oracle.sign_settlement(record, chain_id=80002)


def test_a_stamped_record_is_signed():
    """The control: real engine output still signs."""
    import match_engine as engine

    record = _settled_record()
    engine.stamp_settlement(record)

    envelope = oracle.sign_settlement(record, chain_id=80002)

    assert envelope["signature"].startswith("0x")


def test_a_forged_stamp_is_refused():
    """The stamp must be a MAC, not a boolean."""
    record = _settled_record()
    record["engineStamp"] = "not-a-real-mac"

    with pytest.raises(ValueError, match="engine"):
        oracle.sign_settlement(record, chain_id=80002)


# --- M8: the signer is loaded once --------------------------------------------
def test_the_signer_is_loaded_once(monkeypatch):
    calls = {"n": 0}
    real = Account.from_key

    def _counting(key):
        calls["n"] += 1
        return real(key)

    monkeypatch.setattr(oracle.Account, "from_key", staticmethod(_counting))

    oracle.load_signer()
    oracle.load_signer()
    oracle.load_signer()

    assert calls["n"] == 1, (
        f"the signer was loaded {calls['n']} times — Account.from_key does an EC "
        "multiplication and is the expensive part of signing (audit M8)"
    )


def test_the_cached_signer_is_the_right_address():
    a = oracle.load_signer()
    b = oracle.load_signer()

    assert a.address == b.address
    assert a.address.lower() == oracle.oracle_address().lower()
