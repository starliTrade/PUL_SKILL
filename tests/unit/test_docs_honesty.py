"""Audit M-17 + M-22 (2026-10-22) — docs that cannot silently rot.

The README carried hand-maintained counts (202/278/81) that were already wrong,
and the repository had no LICENSE and no SECURITY.md at all: a product asking
people for money could not state its licence or how to report a vulnerability.

These tests do not measure the suites (that is `scripts/test_counts.py`); they
pin that the numbers come from a RUN, that the licence exists, and that the
security policy tells a researcher how to reach us.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_license_exists_and_is_a_real_license():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "WITHOUT WARRANTY" in text
    # The grant covers code, not the right to run a regulated money game.
    assert "regulated" in text.lower()


def test_the_security_policy_says_where_to_report():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security@" in text
    assert "72 hours" in text
    assert "Do not open a public issue" in text


def test_the_security_policy_points_at_the_known_weaknesses():
    """A policy that pretends there are none invites duplicate reports."""
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "RUTHLESS-AUDIT-2026-10-22" in text
    assert "REMEDIATION-TODO-2026-10-22" in text


def test_the_readme_counts_say_they_are_measured():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "test_counts.py" in text, (
        "the README must name the script that regenerates its numbers (M-17)"
    )
    # And it must not claim a forge result that this repository never produced.
    # Audit M-11 follow-up (2026-10-23): Foundry became runnable here, so the row
    # may now carry a real measurement — but only one that names its date and the
    # word "measured", so a hand-written number still fails this gate.
    # Two contract rows now: the `default` profile and the `nightly` one, each
    # naming its own budget and measurement (2026-10-23).
    row = [ln for ln in text.splitlines() if ln.startswith("| Contract (forge")]
    assert len(row) == 2, f"expected a default and a nightly contract row, found {len(row)}"
    measured = re.search(r"measured (\d{4}-\d{2}-\d{2})", row[0])
    assert "not run here" in row[0] or "CI" in row[0] or measured, (
        "the forge row must either say it was not run here, point at CI, or carry a "
        "dated measurement"
    )
    if measured:
        assert re.search(r"\d+ tests", row[0]), "a measured row must state the test count"


def test_the_count_script_refuses_to_invent_the_contract_number():
    source = (ROOT / "scripts" / "test_counts.py").read_text(encoding="utf-8")
    assert "forge test" in source
    assert "not measurable here" in source


def test_how_it_works_does_not_claim_an_unverifiable_finding_count():
    """Audit L-05 — "۵۳ یافته رفع‌شده" was a number with no evidence behind it.

    The audit listed it as an unverified claim; it is exactly the kind of
    sentence that is true when written and a lie six commits later. The document
    may describe behaviour, and it may point at the itemised table — it may not
    assert a bare total.
    """
    text = (ROOT / "docs" / "HOW-IT-WORKS.md").read_text(encoding="utf-8")
    assert "۵۳ یافته" not in text
    assert "REMEDIATION-TODO-2026-10-22.md" in text, "the status must name its evidence"
