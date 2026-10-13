"""
Phase 7 / M19 + M20 + M21 — the oracle id, the fee override, and float money.

**M19.** `_match_id_bytes32` treats any 64-character id as hex and calls
`bytes.fromhex`. A 64-character id that is NOT hex — a client-supplied string,
or a server id that happens to be 64 chars — raises `ValueError` and takes the
signing path down with it. The convention is "64 hex chars OR hash it", and the
second branch must actually be reachable.

**M20.** `_winner_share()` reads `PLATFORM_FEE_BPS` from the environment. The
CONTRACT's `PLATFORM_FEE_BPS` is the on-chain authority — it is what actually
splits the money. An env override makes the server's ledger disagree with the
chain, so a player's recorded prize differs from what they received, and the
discrepancy is invisible until someone reconciles.

**M21.** `prize = round(stake * 2 * _winner_share(), 2)` is float arithmetic on
money. `round` on a float is not the same as rounding in base units: 0.1 + 0.2
is not 0.3, and a prize computed in floats can differ from the on-chain integer
by a base unit. The ledger then records a number the chain never paid.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import economy  # noqa: E402
import oracle  # noqa: E402


# --- M19 ----------------------------------------------------------------------
def test_a_64_char_non_hex_id_is_hashed_not_crashed():
    """The hash branch must be reachable for a 64-char non-hex id."""
    weird = "z" * 64

    out = oracle._match_id_bytes32(weird)

    assert len(out) == 32, "a 64-char non-hex id must be hashed, not raise"


def test_a_64_char_hex_id_is_decoded():
    """The control: a real hex id is still decoded as bytes."""
    hex_id = "ab" * 32

    out = oracle._match_id_bytes32(hex_id)

    assert out == bytes.fromhex(hex_id)


def test_a_short_id_is_hashed():
    out = oracle._match_id_bytes32("short-id")

    assert len(out) == 32


def test_the_convention_matches_the_client():
    """The server and the client must derive the SAME bytes32 for the same id."""
    import hashlib

    for match_id in ("ab" * 32, "z" * 64, "short", "0x" + "cd" * 32):
        expected = (
            bytes.fromhex(match_id.lower().removeprefix("0x"))
            if len(match_id.lower().removeprefix("0x")) == 64
            and all(c in "0123456789abcdef" for c in match_id.lower().removeprefix("0x"))
            else hashlib.sha256(match_id.encode("utf-8")).digest()
        )
        assert oracle._match_id_bytes32(match_id) == expected


# --- M20 ----------------------------------------------------------------------
def test_the_fee_cannot_be_overridden_by_env(monkeypatch):
    """The contract is the authority; the server must mirror it, not outvote it."""
    monkeypatch.setenv("PLATFORM_FEE_BPS", "5000")

    share = economy._winner_share()

    assert share == pytest.approx(0.98), (
        f"PLATFORM_FEE_BPS from the environment changed the winner share to "
        f"{share} — the server's ledger now disagrees with the chain (audit M20)"
    )


def test_the_winner_share_matches_the_contract_constant():
    """Pinned against the Solidity source, like the client's constants."""
    sol = (Path(__file__).resolve().parents[2] / "contracts" / "PulsarEscrow.sol").read_text()
    import re

    m = re.search(r"PLATFORM_FEE_BPS\s*=\s*(\d+)", sol)
    assert m, "PLATFORM_FEE_BPS not found in PulsarEscrow.sol"
    fee_bps = int(m.group(1))

    assert economy._winner_share() == pytest.approx((10_000 - fee_bps) / 10_000)


# --- M21 ----------------------------------------------------------------------
def test_the_prize_is_computed_in_base_units():
    """Money must not be rounded in floats."""
    # 1.005 USDT at 6 decimals: float rounding gets this wrong.
    prize = economy.prize_in_units(stake_units=1_005_000, decimals=6)

    # 2 * 1.005 = 2.01 USDT, 98% = 1.9698 USDT = 1_969_800 units.
    assert prize == 1_969_800, f"expected 1969800 base units, got {prize}"


def test_the_prize_is_exact_for_an_awkward_stake():
    """A stake whose 98% is not representable in binary floating point."""
    # 0.01 USDT = 10_000 units. 2 * 0.01 = 0.02, 98% = 0.0196 = 19_600 units.
    assert economy.prize_in_units(stake_units=10_000, decimals=6) == 19_600

    # 0.07 USDT = 70_000 units -> 0.14 -> 0.1372 = 137_200 units.
    assert economy.prize_in_units(stake_units=70_000, decimals=6) == 137_200


def test_the_prize_never_exceeds_the_pool():
    """A sanity bound: the winner cannot take more than both stakes."""
    for units in (1_000_000, 5_000_000, 10_000_000, 999_999):
        prize = economy.prize_in_units(stake_units=units, decimals=6)
        assert 0 < prize <= 2 * units
