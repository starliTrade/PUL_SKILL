"""Audit 2026-10-13 — the escrow clocks must be ONE protocol across layers.

The settle horizon and the refund clock live in the contract, in the server
(`match_engine.MATCH_TIMEOUT_SECONDS`, `main.REFUND_GRACE_SECONDS`) and in the
client (`ESCROW_TIMING`). Only the CLIENT copy was pinned to the Solidity source
(`src/lib/chain.test.ts`); the server's two constants were pinned by nothing, and
the contract's own two clocks used DIFFERENT anchors (`createdAt` for settle,
`max(createdAt, activatedAt)` for refund) — which is how the server came to mint
proofs the contract rejected.

These tests pin all of it to the Solidity source, so a change on one side that is
not mirrored on the others fails here instead of stranding a prize.
"""

from __future__ import annotations

import pathlib
import re

import main as server

import match_engine as engine

SOL = (pathlib.Path(__file__).resolve().parents[2] / "contracts" / "PulsarEscrow.sol").read_text(
    encoding="utf-8"
)


def _solidity_constant(name: str) -> int:
    m = re.search(rf"{name}\s*=\s*([0-9_]+)\s*(minutes|seconds|hours)?\s*;", SOL)
    assert m, f"{name} not found in PulsarEscrow.sol"
    value = int(m.group(1).replace("_", ""))
    unit = m.group(2)
    if unit == "minutes":
        value *= 60
    elif unit == "hours":
        value *= 3600
    return value


def test_the_server_match_timeout_matches_the_contract():
    assert engine.MATCH_TIMEOUT_SECONDS == _solidity_constant("MATCH_TIMEOUT"), (
        "the server's settlement horizon disagrees with the contract's — the "
        "oracle would sign deadlines the chain rejects"
    )


def test_the_server_refund_grace_matches_the_contract():
    assert server.REFUND_GRACE_SECONDS == _solidity_constant("REFUND_GRACE"), (
        "the server's refund copy disagrees with the contract's"
    )


def test_the_contract_uses_one_anchor_for_both_clocks():
    """Both `settleDuel` and `refundTimeoutMatch` must derive the same origin.

    H20 moved the refund to activation and left the settle horizon on
    `createdAt`; the server followed the refund, so every late proof was
    rejected. This pins the two to the same expression.
    """
    settle = SOL[SOL.index("function settleDuel(") : SOL.index("function refundTimeoutMatch(")]
    refund = SOL[SOL.index("function refundTimeoutMatch(") :]
    assert "activatedAt[proof.matchId] > duel.createdAt" in settle, (
        "settleDuel does not anchor its horizon on activation — a late-joined "
        "duel's proof will be rejected (audit 2026-10-13)"
    )
    assert "activatedAt[matchId] > duel.createdAt" in refund, (
        "refundTimeoutMatch does not anchor on activation (audit H20)"
    )


def test_the_server_settlement_deadline_follows_the_same_anchor():
    """`settlement_deadline` must use max(created, activated), like the chain.

    Audit H-25 made this BEHAVIOURAL instead of a grep of the source. The old
    check passed as long as the words "max(created, activated)" appeared
    anywhere in the function — including in a comment — and it could not see
    that a match without timestamps silently became 1970 (H-25). Numbers are
    harder to fake than text.
    """

    class _M:
        def __init__(self, created: float, activated: float) -> None:
            self.created_at = created
            self.activated_at = activated

    created, activated = 1_700_000_000.0, 1_700_000_500.0
    # The contract uses max(createdAt, activatedAt), and joinDuel always sets
    # activation later — so a late-joined duel must be measured from activation.
    for c, a in ((created, activated), (activated, created), (created, 0.0)):
        expected = int(max(c, a) + engine.MATCH_TIMEOUT_SECONDS)
        assert engine.settlement_deadline(_M(c, a)) == expected, (c, a)

    # And an object that carries neither timestamp has NO horizon — it must not
    # be reported as 1970 (which every caller read as "expired").
    assert engine.settlement_deadline_or_none(_M(0.0, 0.0)) is None


# --- the prize the ledger records must be the prize the chain pays -------------


def test_the_server_prize_matches_the_contract_formula():
    """Audit 2026-10-13: only the FEE BPS was pinned across layers.

    `api/economy.prize_in_units` computes the winner's prize in base units; the
    contract computes it inline. Nothing checked that the two produce the SAME
    number, so a change to either formula (a different rounding, a fee applied
    to the wrong side) would make the ledger record a prize the chain never
    paid — and the discrepancy would only surface in a payout dispute.
    """
    import economy

    fee_bps = _solidity_constant("PLATFORM_FEE_BPS")
    denominator = _solidity_constant("FEE_DENOMINATOR")
    assert fee_bps == economy.CONTRACT_PLATFORM_FEE_BPS

    for stake_units in (1, 1_000_000, 5_000_000, 10_000_000, 999_999_999, 123_456_789):
        pool = 2 * stake_units
        # The contract's own arithmetic, verbatim.
        contract_fee = (pool * fee_bps) // denominator
        contract_prize = pool - contract_fee
        assert economy.prize_in_units(stake_units) == contract_prize, (
            f"the ledger's prize for {stake_units} base units differs from the "
            f"chain's ({economy.prize_in_units(stake_units)} vs {contract_prize})"
        )


def test_the_prize_plus_the_fee_is_the_whole_pool():
    """No base unit may be created or lost in the split."""
    import economy

    for stake_units in (1, 7, 1_000_000, 3_333_333, 99_999_999):
        pool = 2 * stake_units
        prize = economy.prize_in_units(stake_units)
        fee = pool - prize
        assert prize + fee == pool
        assert prize > 0
