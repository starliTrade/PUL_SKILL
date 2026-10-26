"""C-02c (2026-10-22) — the compliance document must stay true to the contract.

`docs/COMPLIANCE-C-02c.md` makes three load-bearing claims about the money path:
`settleDuel` pays immediately, `createDuel`/`joinDuel` are permissionless, and
there is therefore no server-side place to hold a payout or to refuse an
unverified player.

Those are facts about Solidity, and a document that states them is only useful
while they are true. If someone adds an allow-list (the C-02c-4 work), the
document becomes wrong — and a wrong compliance document is worse than none,
because people plan around it. These tests fail in that case and force the
document to be updated in the same change.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "PulsarEscrow.sol"
DOC = ROOT / "docs" / "COMPLIANCE-C-02c.md"


def _source() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    source = _source()
    start = source.index(f"function {name}(")
    # Crude but sufficient: the next top-level `function` keyword ends the body.
    end = source.find("\n    function ", start + 1)
    return source[start : end if end != -1 else len(source)]


def test_the_document_exists_and_states_that_it_is_not_implemented():
    text = DOC.read_text(encoding="utf-8")
    assert "پیاده‌سازی نشده" in text, (
        "a compliance document must say whether the controls exist or are only "
        "specified — a reader will otherwise assume KYC is live"
    )


def test_settlement_still_pays_immediately_and_the_doc_says_so():
    body = _function_body("settleDuel")
    pays_inline = "_pay(proof.winner" in body
    assert pays_inline, (
        "settleDuel no longer pays the winner directly — C-02c §1 claims it does. "
        "If a payout hold was added, update docs/COMPLIANCE-C-02c.md (decision 2) "
        "instead of deleting this test."
    )
    text = DOC.read_text(encoding="utf-8")
    assert "settleDuel" in text and "پرداخت" in text


def test_the_duel_entry_points_are_still_permissionless():
    for name in ("createDuel", "joinDuel"):
        body = _function_body(name)
        has_gate = bool(
            re.search(r"allow-?list|allowlist|whitelist|kyc|KYC|hasRole|onlyRole", body)
        )
        assert not has_gate, (
            f"{name} now has an access gate. docs/COMPLIANCE-C-02c.md §1 says the "
            "contract is permissionless and that a server-only control can be "
            "bypassed; update the document before changing this expectation."
        )


def test_the_readme_warns_before_it_sells_anything():
    """A repository that reads like a finished product will be deployed as one."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    head = readme[:2000]
    assert "TESTNET ONLY" in head, "the README must open with the deployment status"
    assert "no KYC" in head.lower() or "not fit for real money" in head.lower()
    assert "COMPLIANCE-C-02c.md" in head


def test_the_document_does_not_claim_any_control_is_implemented():
    text = DOC.read_text(encoding="utf-8")
    forbidden = [
        "KYC حل شد",
        "تأخیر پرداخت ممکن است",
        "دور زدن ممکن نیست",
    ]
    for phrase in forbidden:
        # The document lists these under "what this document does NOT claim".
        assert f"«{phrase}»" in text, (
            f"the honest-limits section must still name {phrase!r}"
        )
