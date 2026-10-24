"""The final report is the first thing a reader opens. Every number in it must be
reproducible, and every "done" must have a test behind it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RAW = (ROOT / "docs" / "FINAL-REPORT.md").read_text(encoding="utf-8")

_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC = "٠١٢٣٤٥٦٧٨٩"


def _latin(text: str) -> str:
    out = []
    for ch in text:
        if ch in _PERSIAN:
            out.append(str(_PERSIAN.index(ch)))
        elif ch in _ARABIC:
            out.append(str(_ARABIC.index(ch)))
        else:
            out.append(ch)
    return "".join(out)


DOC = _latin(_RAW)


def test_the_documents_it_points_at_exist() -> None:
    named = set(re.findall(r"`(docs/[\w./-]+\.md)`", DOC))
    assert len(named) >= 6, "the report should point at every reference document"
    missing = sorted(n for n in named if not (ROOT / n).is_file())
    assert not missing, f"the report cites documents that do not exist: {missing}"


def test_the_test_files_it_names_exist() -> None:
    named = set(re.findall(r"`(tests/[\w./-]+\.py)`", DOC))
    missing = sorted(n for n in named if not (ROOT / n).is_file())
    assert not missing, f"the report cites test files that do not exist: {missing}"


def test_it_names_the_one_open_item_and_only_that_one() -> None:
    doc = (ROOT / "docs/audit/REMEDIATION-TODO-2026-10-22.md").read_text(encoding="utf-8")
    unticked = re.findall(r"^- \[ \] \*\*([A-Z]-[0-9]+[a-z]?)\*\*", doc, re.M)
    assert unticked == ["C-02c"], unticked
    assert "`C-02c`" in DOC or "C-02c" in DOC
    # And the count it quotes must be the count the list has. UNIQUE ids, because
    # H-17 and H-18 each carry two findings (the collision is documented in the
    # list itself and guarded by test_remediation_todo_consistency).
    ticked_ids = set(re.findall(r"^- \[x\] \*\*([A-Z]-[0-9]+[a-z]?)\*\*", doc, re.M))
    total = len(ticked_ids) + len(set(unticked))
    assert f"**{len(ticked_ids)} شناسهٔ یکتا از {total}**" in DOC, (
        f"the report's ratio does not match the list: {len(ticked_ids)} of {total}"
    )


def test_it_does_not_claim_the_app_is_ready_for_real_money() -> None:
    # The single most important sentence in the document.
    assert "آماده برای پول واقعی؟ | **نه.**" in DOC
    assert "No-Go" in DOC


def test_it_admits_what_was_not_run() -> None:
    for phrase in ("Playwright", "Firestore emulator", "Amoy", "ممیزی بیرونی"):
        assert phrase in DOC
    assert "اجرا نشد" in DOC or "اجرا نشده" in DOC


def test_the_gate_table_uses_the_counts_the_suite_reports() -> None:
    # Cross-checks against files that are themselves enforced by other tests:
    # README's measured table and the coverage config's floor.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"Server \(pytest\) \| (\d+) passed / (\d+) skipped with anvil running", readme)
    assert m, "README lost its measured pytest row"
    assert f"**{m.group(1)} pass / {m.group(2)} skip**" in DOC, (
        f"the report and README disagree about pytest ({m.group(1)}/{m.group(2)})"
    )
    v = re.search(r"Frontend \(vitest\) \| (\d+) tests, (\d+) files", readme)
    assert v
    assert f"**{v.group(1)} / {v.group(2)} فایل**" in DOC

    floor = re.search(r"^fail_under\s*=\s*(\d+)",
                      (ROOT / ".coveragerc-hermetic").read_text(encoding="utf-8"), re.M)
    assert floor
    assert f"کف **{floor.group(1)}**" in DOC
