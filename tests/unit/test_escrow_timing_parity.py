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
    """`settlement_deadline` must use max(created, activated), like the chain."""
    src = pathlib.Path(engine.__file__).read_text(encoding="utf-8")
    body = src[src.index("def settlement_deadline(") : src.index("def settlement_deadline(") + 900]
    assert "max(created, activated)" in body, (
        "the server's settlement deadline no longer follows the contract's anchor"
    )
