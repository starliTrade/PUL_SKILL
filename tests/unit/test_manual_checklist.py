"""The manual checklist tells a human to type commands. If one of them is wrong,
the human types it, it fails, and the runbook loses credibility on step one.

These tests check the checklist against the repository instead of trusting it:
every script it invokes exists, every flag it passes is one the script declares,
every marker it filters on exists, and the counts it quotes match reality.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RAW_DOC = (ROOT / "docs" / "MANUAL-CHECKLIST.md").read_text(encoding="utf-8")

_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC = "٠١٢٣٤٥٦٧٨٩"


def _latin(text: str) -> str:
    """The document is Persian and writes its numbers in Persian digits.

    The comparison is about the VALUE; the numeral style of a doc is the author's
    choice (the Latin-digit policy in `src/lib/localeFormat.ts` is about the UI,
    where a number must survive copy-paste into a block explorer).
    """
    out = []
    for ch in text:
        if ch in _PERSIAN:
            out.append(str(_PERSIAN.index(ch)))
        elif ch in _ARABIC:
            out.append(str(_ARABIC.index(ch)))
        else:
            out.append(ch)
    return "".join(out)


DOC = _latin(_RAW_DOC)


def _scripts_mentioned() -> set[str]:
    return set(re.findall(r"(scripts/[\w./-]+\.(?:sh|py))", DOC))


def test_every_script_it_names_exists() -> None:
    named = _scripts_mentioned()
    assert named, "the checklist names no scripts at all"
    missing = sorted(n for n in named if not (ROOT / n).is_file())
    assert not missing, f"the checklist tells a human to run scripts that do not exist: {missing}"


def test_the_keeper_flags_it_uses_are_real() -> None:
    src = (ROOT / "scripts" / "keeper.py").read_text(encoding="utf-8")
    for flag in re.findall(r"keeper\.py([^`\n]*)", DOC):
        for opt in re.findall(r"--[\w-]+", flag):
            assert f'"{opt}"' in src, f"keeper.py has no {opt}"


def test_the_chaos_scenario_names_are_real() -> None:
    src = (ROOT / "scripts" / "chaos_suite.py").read_text(encoding="utf-8")
    listed = re.search(r"\(نام‌ها: ([^)]+)\)", DOC)
    assert listed, "the checklist no longer lists the chaos scenario names"
    names = re.findall(r"`([a-z_]+)`", listed.group(1))
    assert names
    for name in names:
        assert f'"{name}"' in src, f"chaos_suite.py has no scenario {name}"


def test_the_pytest_markers_it_filters_on_are_registered() -> None:
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8") if (ROOT / "pytest.ini").is_file() else ""
    cfg = ini or (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for marker in ("chain", "emulator"):
        assert marker in cfg, f"marker {marker} is not registered"


def test_the_counts_it_quotes_are_the_ones_this_repo_collects() -> None:
    def collected(expr: str) -> int:
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", expr, "--co"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        match = re.search(r"(\d+)/\d+ tests collected", out)
        assert match, out[-400:]
        return int(match.group(1))

    assert collected("chain") == 11, "the checklist says 11 chain tests"
    assert "**11 passed**" in DOC
    emulator = collected("emulator or firestore")
    assert emulator == 17, f"the checklist says 17 emulator tests, {emulator} are collected"
    assert "**17 passed، 0 skip**" in DOC


def test_the_gate_count_is_the_script_s_gate_count() -> None:
    script = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    gates = len(re.findall(r'^\s*run_gate "', script, re.M))
    skips = len(re.findall(r'\s*skip_gate "', script))
    assert f"**{gates} گیت**" in DOC, f"verify.sh has {gates} gates"
    assert f"{skips} جای دیگر `skip_gate`" in DOC, f"verify.sh has {skips} skip_gate calls"


def test_it_does_not_pretend_a_never_run_step_passed() -> None:
    # The three things this environment could not execute are named as such.
    for phrase in ("انجام‌نشده", "هرگز اجرا نکرد", "در sandbox"):  # Persian: not done / never ran / in sandbox
        assert phrase in DOC, f"the checklist lost its admission: {phrase}"
