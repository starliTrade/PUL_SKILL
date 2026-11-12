"""The coverage report must not quote numbers nothing can reproduce.

`docs/COVERAGE-REPORT.md` exists because one percentage invites the wrong
conclusion. It is only better than a raw percentage if its own claims hold:

  * the floor in `.coveragerc-hermetic` is the one the document quotes;
  * every module percentage it prints is either measured here or marked as not
    measured;
  * the "closed" claim names a test file that exists and really tests the
    function it says it tests.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "COVERAGE-REPORT.md"
HERMETIC = ROOT / ".coveragerc-hermetic"


def _text() -> str:
    assert DOC.is_file(), "docs/COVERAGE-REPORT.md is missing"
    return DOC.read_text(encoding="utf-8")


def test_the_floor_it_quotes_is_the_floor_in_the_config() -> None:
    match = re.search(r"^fail_under\s*=\s*(\d+)", HERMETIC.read_text(encoding="utf-8"), re.M)
    assert match, ".coveragerc-hermetic has no fail_under"
    floor = match.group(1)
    # The floor lives in the last column of §2's history table (it moved
    # 74 -> 77 -> 78); the assertion reads that column rather than one literal
    # string, so the report cannot drift from the config without failing.
    row = next(ln for ln in _text().splitlines() if ln.startswith("| floor |"))
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    assert cells[-1] == f"**{floor}**", f"the report does not say the floor is now {floor}"


def test_it_says_what_it_did_NOT_measure() -> None:
    text = _text()
    assert "It was\nnot measured here" in text or "not measured here" in text, (
        "the report must admit that the complete (emulator) gate was not measured"
    )
    assert "79" in text, "the complete gate's floor must be named"


def test_the_closed_gap_names_a_real_test_with_real_cases() -> None:
    text = _text()
    assert "verify_settlement_tx" in text
    test_file = ROOT / "tests" / "unit" / "test_claim_verification.py"
    assert test_file.is_file(), "the report claims a test file that does not exist"
    cases = [ln for ln in test_file.read_text(encoding="utf-8").splitlines() if ln.startswith("def test_")]
    assert len(cases) >= 15, f"the report claims 15 cases, the file has {len(cases)}"
    assert "15 cases" in text


def test_every_environmental_gap_names_a_command_or_a_service() -> None:
    """A gap with no way to close it is a shrug; the table must offer one."""
    section = _text().split("### 3.1")[1].split("### 3.2")[0]
    for needle in ("start_emulator.sh", "KMS", "cloud account"):
        assert needle in section, f"the environmental table lost its remedy for {needle}"


def test_the_document_is_linked_from_the_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "COVERAGE-REPORT.md" in readme, "a document nobody can find is a scratch file"
