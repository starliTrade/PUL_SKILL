"""`docs/CONTRACT-FUZZ-REPORT.md` quotes numbers from a 21-minute run.

A number nobody can re-derive is a rumour. These tests check the parts that ARE
derivable from the repository: the profile's budgets, the arithmetic from those
budgets to the call counts the report prints, the nightly job that is supposed to
select those budgets in CI, and the admission the report makes about what the
pass cannot see. The measured wall clock and revert rates come from one run and
are cited as such.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOML = (ROOT / "contracts" / "foundry.toml").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "CONTRACT-FUZZ-REPORT.md").read_text(encoding="utf-8")
INVARIANTS = (ROOT / "contracts" / "test" / "PulsarEscrowInvariants.t.sol").read_text(
    encoding="utf-8"
)
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _nightly(section: str, key: str) -> int:
    block = TOML.split(f"[profile.nightly.{section}]", 1)[1].split("[", 1)[0]
    match = re.search(rf"^{key}\s*=\s*(\d+)", block, re.M)
    assert match, f"nightly {section}.{key} is not set"
    return int(match.group(1))


def _invariant_names() -> list[str]:
    names = re.findall(r"function (invariant_\w+)\(", INVARIANTS)
    # The control contract holds non-invariant tests only, but a helper named
    # `invariant_...` inside it would still be executed by forge, so count them
    # all rather than guessing.
    return names


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
    names = _invariant_names()
    assert len(names) == 7, f"the report says seven properties, the file has {len(names)}"
    total = len(names) * calls_per_property
    assert total == 3_584_000
    assert "**3,584,000 randomized calls**" in DOC or "3.58 million" in DOC
    # The historical run (six properties, 3,072,000 calls) stays in the record and
    # must still be labelled as that run, not silently rewritten.
    assert "**3,072,000 randomized calls**" in DOC
    assert "2026-10-23" in DOC


def test_the_revert_weakness_is_closed_and_the_closure_is_verifiable() -> None:
    # Section 4 used to be an admission. It must now be a closure that names the
    # mechanism, and the mechanism must still exist in the source.
    assert "closed 2026-10-24" in DOC
    assert "invariant_no_unexpected_reverts" in INVARIANTS
    assert "invariant_no_unexpected_reverts()" in DOC
    assert "catch (bytes memory reason)" in INVARIANTS
    assert "EscrowHandlerRevertControl" in INVARIANTS
    assert "EscrowHandlerRevertControl" in DOC
    # "no allowlist" must stay explicit: an allowlist of tolerated reasons is the
    # weaker design that was rejected.
    assert "no allowlist" in DOC.lower()


def test_there_is_no_tolerated_revert_left_in_the_handler() -> None:
    # The old escape hatch: `fail_on_revert = false` plus a permissive allowlist.
    # The property is only as strong as the fact that NOTHING is permitted, so
    # assert the recorded count is compared to zero rather than to a list.
    body = INVARIANTS.split("function invariant_no_unexpected_reverts", 1)[1].split(
        "function ", 1
    )[0]
    assert "revertCount()" in body
    assert "!= 0" in body
    assert "firstRevertIn()" in body


def test_the_deep_profile_actually_runs_in_ci() -> None:
    # Audit 2026-10-24: `[profile.nightly]` was selected by nothing — not a
    # workflow, not `scripts/verify.sh`. A profile that no job selects is a
    # comment, so this test fails if the wiring is ever removed.
    assert "nightly-contracts:" in CI, "the nightly job is gone from ci.yml"
    job = CI.split("nightly-contracts:", 1)[1]
    assert re.search(r"^\s+schedule:", CI, re.M), "no schedule trigger"
    assert re.search(r"cron:\s*'0 3 \* \* \*'", CI), "the cron line moved"
    assert "workflow_dispatch:" in CI
    assert "FOUNDRY_PROFILE: nightly" in job
    # The job must not be a PR gate: it is the slow one.
    assert "if: github.event_name == 'schedule'" in job
    # And it must prove the deep budgets are in force — a default-budget run in a
    # job called "nightly" looks identical from the outside.
    assert "tomllib" in job
    assert "10000" in job


def test_it_does_not_claim_the_pass_is_stronger_than_it_is() -> None:
    # The document must keep a "does not prove" section. If that ever disappears,
    # the file becomes marketing.
    assert "does not prove" in DOC.lower()
    assert "does not" in DOC.lower()


def test_every_property_it_names_exists() -> None:
    named = set(re.findall(r"`(invariant_\w+)`", DOC))
    assert named, "the report names no invariant properties"
    missing = sorted(p for p in named if f"function {p}(" not in INVARIANTS)
    assert not missing, f"the report names properties that do not exist: {missing}"
