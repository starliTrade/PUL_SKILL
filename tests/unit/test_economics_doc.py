"""Audit M-12 — the fee model is fixed, and the product copy has to tell the truth about it.

The audit accepted the risk ("the fee is a constant, changing it needs a
redeploy") on the condition that the decision be explicit in a product document.
`docs/ECONOMICS.md` is that document. This module keeps it honest:

  * the numbers in the document are recomputed from the contract and from the
    client and must match — a fee table that drifts from the code is worse than
    no table, because it is what support and marketing quote;
  * the claim "there is no fee setter" is checked against the Solidity source,
    so nobody can quietly add the flexibility this decision rejected;
  * all five localized "98 % payout · 2 % fee" strings must state the real
    split, because that is the promise made to every player in their language.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "PulsarEscrow.sol"
CHAIN_TS = ROOT / "src" / "lib" / "chain.ts"
I18N = ROOT / "src" / "i18n" / "translations.ts"
DOC = ROOT / "docs" / "ECONOMICS.md"


def _contract_src() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _fee_bps() -> int:
    match = re.search(r"uint256 public constant PLATFORM_FEE_BPS = (\d+);", _contract_src())
    assert match, "PLATFORM_FEE_BPS not found"
    return int(match.group(1))


def _denominator() -> int:
    match = re.search(r"uint256 public constant FEE_DENOMINATOR = (\d+);", _contract_src())
    assert match, "FEE_DENOMINATOR not found"
    return int(match.group(1))


def _doc() -> str:
    assert DOC.exists(), "docs/ECONOMICS.md is missing — audit M-12 requires it"
    return DOC.read_text(encoding="utf-8")


# --- 1. the numbers ----------------------------------------------------------
def test_the_document_quotes_the_contract_constants():
    doc = _doc()
    fee = _fee_bps()
    assert fee == 200, "the documented model is 2%; changing it means updating ECONOMICS.md"
    assert f"{fee} bps" in doc
    assert f"{_denominator():,}".replace(",", " ") in doc or str(_denominator()) in doc
    assert f"| {fee} bps = {fee / 100:.2f} %" in doc or f"{fee / 100:.2f} %" in doc


def test_the_client_agrees_with_the_contract():
    src = CHAIN_TS.read_text(encoding="utf-8")
    fee = re.search(r"platformFeeBps: (\d+),", src)
    share = re.search(r"winnerShareBps: 10_000 - (\d+),", src)
    assert fee and share, "ECONOMY constants not found in chain.ts"
    assert int(fee.group(1)) == _fee_bps()
    assert int(share.group(1)) == _fee_bps()
    assert 10_000 - _fee_bps() == 10_000 - int(fee.group(1))


def test_the_worked_examples_are_arithmetically_right():
    # Recompute every row of the table and require the document to contain the
    # exact values. Floor division, as in Solidity: `pool * bps / denominator`.
    doc = _doc()
    fee_bps, denom = _fee_bps(), _denominator()
    for stake in (1, 2, 5, 10):
        pool_units = stake * 2 * 1_000_000
        fee_units = pool_units * fee_bps // denom
        prize_units = pool_units - fee_units
        assert f"| {stake} USDT | {stake * 2:.2f} | {fee_units / 1e6:.2f} | **{prize_units / 1e6:.2f}**" in doc, (
            f"the worked example for a {stake} USDT stake does not match the contract"
        )
        # and the net profit column
        net = (prize_units - stake * 1_000_000) / 1e6
        assert f"+{net:.2f}" in doc


def test_the_document_states_the_real_timelock():
    match = re.search(r"uint256 public constant ADMIN_TIMELOCK = (\d+) days;", _contract_src())
    assert match, "ADMIN_TIMELOCK not found"
    assert f"timelocked {match.group(1)} days" in _doc()


# --- 2. the rejected flexibility --------------------------------------------
def test_the_contract_has_no_fee_setter():
    src = _contract_src()
    for forbidden in (
        "function setFee",
        "function setPlatformFee",
        "function updateFee",
        "function setFeeBps",
        "function setRake",
    ):
        assert forbidden not in src, (
            f"{forbidden}() re-introduces the mutable rake audit M-12 rejected — "
            "see docs/ECONOMICS.md §2"
        )
    # The constant must stay a constant, not a storage variable an owner writes.
    assert "uint256 public constant PLATFORM_FEE_BPS" in src
    assert not re.search(r"PLATFORM_FEE_BPS\s*=", src.replace("PLATFORM_FEE_BPS = 200", ""))


def test_the_treasury_is_not_withdrawable_by_the_owner():
    # Fee revenue never sits in a pot: it is transferred at settlement. The only
    # token-moving admin functions are the timelocked treasury rotation and the
    # frozen-only residual sweep (which cannot reach player money).
    src = _contract_src()
    assert "function sweepResidual" in src
    sweep_body = src.split("function sweepResidual(", 1)[1].split("\n    }", 1)[0]
    assert "residualBalance()" in sweep_body
    assert 'require(frozen, "Not frozen")' in sweep_body
    assert "treasuryWallet" not in sweep_body


# --- 3. product copy --------------------------------------------------------
# The numeral policy (i18n audit, 2026-10-23): every number the UI renders is a
# Latin digit, in all five languages, because the amounts sit beside addresses,
# hashes and `font-mono` columns that cannot follow a locale. This table used to
# assert Persian digits for `fa` and Arabic-Indic for `ar` — which the product
# only ever did in STATIC copy, never for a dynamic value, so the same screen
# showed two systems. See docs/I18N-AUDIT.md §4.
_LOCALE_DIGITS = {
    "ascii": str.maketrans("0123456789", "0123456789"),
}


def _localized_platform_fee_strings() -> list[str]:
    src = I18N.read_text(encoding="utf-8")
    return re.findall(r"^\s{4}platformFee: '(.*)',$", src, flags=re.MULTILINE)


def test_every_locale_states_the_real_split():
    fee = _fee_bps() / 100  # 2.0
    share = (10_000 - _fee_bps()) / 100  # 98.0
    values = _localized_platform_fee_strings()
    assert len(values) == 5, f"expected 5 locales, found {len(values)}"

    styles = ["ascii"] * 5  # en, fa, ar, tr, zh — one numeral system
    for style, value in zip(styles, values, strict=True):
        digits = _LOCALE_DIGITS[style]
        # And the string must not smuggle in a locale digit either: that was the
        # half of this table that used to pass by design.
        assert not re.search("[\u06F0-\u06F9\u0660-\u0669]", value), value
        fee_txt = f"{fee:g}".translate(digits)
        share_txt = f"{share:g}".translate(digits)
        # Turkish writes the percent sign first ("%2"), the rest after.
        assert f"{fee_txt}%" in value or f"{fee_txt}٪" in value or f"%{fee_txt}" in value, value
        assert f"{share_txt}%" in value or f"{share_txt}٪" in value or f"%{share_txt}" in value, value


# --- 4. the decision record ------------------------------------------------
def test_the_document_is_a_decision_record_not_a_brochure():
    doc = _doc().lower()
    for required in (
        "upgrade-path.md",  # how a change actually ships
        "setfeebps",  # the alternative that was rejected, by name
        "multisig",  # the deployment requirement on the treasury
        "revisit",  # a trigger to re-open the decision
    ):
        assert required in doc, f"ECONOMICS.md never mentions {required}"


def test_the_document_is_explicit_that_l1_is_not_viable():
    # The gas table is the finding that decides where this can be deployed. If
    # someone deletes it, the next person deploys the 1 USDT ladder to L1.
    doc = _doc()
    assert "Do not deploy the current stake ladder to L1" in doc
    assert "gwei" in doc
    assert "break-even" in doc
