"""`docs/CONTRACT-FUZZ-REPORT.md` quotes numbers from a 21-minute run.

A number nobody can re-derive is a rumour. These tests check the parts that ARE
derivable from the repository: the profile's budgets, the arithmetic from those
budgets to the call counts the report prints, and the admission the report makes
about what the pass cannot see. The measured wall clock and revert rates come
from one run and are cited as such.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOML = (ROOT / "contracts" / "foundry.toml").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "CONTRACT-FUZZ-REPORT.md").read_text(encoding="utf-8")


def _nightly(section: str, key: str) -> int:
    block = TOML.split(f"[profile.nightly.{section}]", 1)[1].split("[", 1)[0]
    match = re.search(rf"^{key}\s*=\s*(\d+)", block, re.M)
    assert match, f"nightly {section}.{key} is not set"
    return int(match.group(1))


def test_the_nightly_profile_still_has_the_budgets_the_report_quotes() -> None:
    runs = _nightly("fuzz", "runs")
    inv_runs = _nightly("invariant", "runs")
    depth = _nightly("invariant", "depth")
    assert (runs, inv_runs, depth) == (10_000, 1_024, 500)
    assert "| **10,000** |" in DOC
    assert "**1,024 × 500 = 512,000 calls**" in DOC


def test_the_call_arithmetic_matches() -> None:
    calls_per_property = _nightly("invariant", "runs") * _nightly("invariant", "depth")
    assert calls_per_property == 512_000
    properties = (ROOT / "contracts" / "test" / "PulsarEscrowInvariants.t.sol").read_text(
        encoding="utf-8"
    )
    names = re.findall(r"function (invariant_\w+)\(", properties)
    assert len(names) == 6, f"the report says six properties, the file has {len(names)}"
    assert f"{len(names) * calls_per_property:,}".replace(",", ",") == "3,072,000"
    assert "**3,072,000 randomized calls**" in DOC


def test_it_does_not_claim_the_pass_is_stronger_than_it_is() -> None:
    # The point of section 4 is that a green run with `fail_on_revert = false`
    # cannot tell an expected revert from a bug. If that caveat is ever removed,
    # the document becomes marketing.
    assert "fail_on_revert = false" in DOC
    assert "cannot distinguish" in DOC
    assert "does not prove" in DOC.lower()


def test_every_property_it_names_exists() -> None:
    properties = (ROOT / "contracts" / "test" / "PulsarEscrowInvariants.t.sol").read_text(
        encoding="utf-8"
    )
    named = set(re.findall(r"`(invariant_\w+)`", DOC))
    assert named, "the report names no invariant properties"
    missing = sorted(p for p in named if f"function {p}(" not in properties)
    assert not missing, f"the report names properties that do not exist: {missing}"
