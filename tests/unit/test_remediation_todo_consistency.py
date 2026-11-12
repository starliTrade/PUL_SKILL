"""The remediation list must not claim work that is done is open (or vice versa).

`docs/audit/REMEDIATION-TODO-2026-10-22.md` is the document a reader uses to
decide what is left. It drifted in both directions: nine items that had landed
(`H-07`, `H-11`, `H-12`, `H-14`, `M-08`, `M-10`, `M-15`, `M-19/M-21/M-22`,
`M-24`) were still unticked, and the line "open items" still listed the whole
M/L series after it had been closed. A status document that is wrong in the
safe-looking direction is still wrong: it makes finished work invisible and
makes the remaining risk unreadable.

These tests check the document against the REPOSITORY, not against a memory of
what was done: every ticked item must have a commit hash that exists, and every
item named in the open list must actually be open.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs/audit/REMEDIATION-TODO-2026-10-22.md").read_text(encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def test_every_cited_commit_exists() -> None:
    """A citation you cannot `git show` is a rumour."""
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        # A depth-1 checkout of the pull-request head has one commit in it, so
        # every citation "does not exist" — a true statement about the clone and
        # useless about the repository. CI was doing exactly that, and this test
        # failed on the first run with 41 hashes that were all present upstream.
        pytest.skip("shallow clone — fetch the full history (actions/checkout fetch-depth: 0)")
    known = set(re.findall(r"\b([0-9a-f]{7})\b", _git("log", "--format=%h", "-n", "400")))
    cited = set(re.findall(r"`([0-9a-f]{7})`", DOC))
    assert cited, "the report cites no commits at all"
    missing = sorted(cited - known)
    assert not missing, f"cited commits not in this repository: {missing}"


def test_the_items_known_to_have_landed_are_ticked() -> None:
    landed = [
        "H-07", "H-11", "H-12", "H-14", "M-08", "M-10", "M-15", "M-24",
        "M-03", "M-04", "M-06", "M-07", "M-14", "M-20", "M-23",
        "L-01", "L-02", "L-04", "L-05", "L-06", "L-07", "L-08", "L-09",
        "L-12", "L-14",
    ]
    for item in landed:
        row = re.search(rf"^- \[([ x])\] \*\*{re.escape(item)}(?:\*\*| )", DOC, re.M)
        assert row, f"{item} has no checkbox line at all"
        assert row.group(1) == "x", f"{item} is marked open but its commit is in the report"


def test_the_open_list_names_only_open_items() -> None:
    line = next(ln for ln in DOC.splitlines() if ln.startswith("**آیتم‌های باز"))
    # Everything still unticked must be a product/environment decision, not code.
    unticked = re.findall(r"^- \[ \] \*\*([A-Z]-\d+[ab]?)", DOC, re.M)
    for item in unticked:
        assert item in line or "خارج از کد" in line, (
            f"{item} is unticked but the open list calls the code work finished"
        )


def test_every_row_that_says_done_names_a_test() -> None:
    """'fixed' without a test name is the claim this whole audit exists to stop.

    Scoped to §4 (the item-by-item table). Other tables in this document list
    external work, where the "test" column does not apply.
    """
    section = DOC.split("## ۴.")[1].split("\n## ")[0]
    rows = [ln for ln in section.splitlines() if ln.startswith("| ") and "✅" in ln]
    assert len(rows) >= 30, f"only {len(rows)} completed rows — the table lost rows"
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) >= 5, row
        assert re.search(r"`[^`]+`|\.test\.|\.t\.sol|probe", cells[3]), (
            f"row claims done with no test artifact: {cells[0]}"
        )

def test_no_identifier_means_two_different_findings() -> None:
    """An audit trail with duplicate ids is not an audit trail.

    Found on 2026-10-24: `H-17` and `H-18` each name TWO unrelated findings —
    the original RUTHLESS-AUDIT ones (`recordMatch`/`history`, `doc_ref.create`)
    and the ones this session found (`store.writable`, memory mode). The history
    is not rewritten (commits and code cite those ids), so the collision is
    documented in the document itself instead.

    This test allows exactly that documented pair and fails on any NEW reuse.
    """
    ids = re.findall(r"^- \[[ x]\] \*\*([A-Z]-[0-9]+[a-z]?)\*\*", DOC, re.M)
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    assert duplicated == ["H-17", "H-18"], (
        f"new identifier reuse: {duplicated}. Give the new finding its own id — a "
        "reader cannot look up an id that means two things"
    )
    # And the collision must stay documented, with both meanings named.
    assert "برخورد شناسه" in DOC
    for meaning in ("store.writable", "recordMatch", "history", "memory"):
        assert meaning in DOC, f"the collision note lost the meaning of {meaning}"
