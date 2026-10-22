"""Audit M-15 (2026-10-22) — the coverage gate must not depend on the environment.

The single gate measured "whatever could run here". With a Firestore emulator up
the integration tests ran and the figure was ~79%; with no emulator they skipped
and it was 74%. Same source, same tests, two different numbers — and a floor of
79 that only holds on a machine that happens to have the emulator started. A
build that is green because of what you had running is not a green build.

The fix is a split, not a lower floor:

  * `.coveragerc-hermetic` — pytest without `emulator`/`chain` markers, with
    FIRESTORE_EMULATOR_HOST explicitly unset. Floor 74, measured on that config.
  * `.coveragerc` — the complete run with the services, floor 79, reported as its
    own gate whose name says what it needs.

These tests pin the SPLIT. The numbers themselves are checked by `verify.sh`,
which is the only place that can actually run the suites.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERMETIC = ROOT / ".coveragerc-hermetic"
COMPLETE = ROOT / ".coveragerc"
VERIFY = ROOT / "scripts" / "verify.sh"


def _floor(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^fail_under\s*=\s*(\d+)", text, re.MULTILINE)
    assert match, f"{path.name} has no fail_under"
    return int(match.group(1))


def test_the_hermetic_gate_exists_and_has_its_own_data_file():
    text = HERMETIC.read_text(encoding="utf-8")
    assert "data_file" in text, (
        "the hermetic run must not share .coverage with the complete run — an "
        "appended session would measure a mix of both configurations"
    )
    assert ".coverage.hermetic" in text


def test_the_hermetic_floor_is_what_that_configuration_actually_reaches():
    assert _floor(HERMETIC) == 74, (
        "raise this floor only in the commit that adds the tests, and only after "
        "a measured run of the hermetic configuration"
    )


def test_the_complete_gate_still_has_its_higher_floor():
    assert _floor(COMPLETE) == 79, "the emulator+anvil run is the one that earns 79"


def test_verify_runs_the_hermetic_gate_first_and_unconditionally():
    script = VERIFY.read_text(encoding="utf-8")
    hermetic_at = script.find("HERMETIC coverage gate")
    complete_at = script.find("COMPLETE coverage gate")
    assert hermetic_at != -1, "verify.sh no longer has a hermetic coverage gate"
    assert complete_at != -1
    assert hermetic_at < complete_at, (
        "the gate that always runs must come first: if the complete gate is first "
        "and the emulator is missing, a skip is all the operator sees"
    )


def test_the_hermetic_run_unsets_the_emulator_variable():
    script = VERIFY.read_text(encoding="utf-8")
    hermetic_block = script[script.find("HERMETIC coverage gate") :][:2000]
    assert "env -u FIRESTORE_EMULATOR_HOST" in hermetic_block, (
        "modules decide to skip by reading FIRESTORE_EMULATOR_HOST at import "
        "time; an inherited value changes what runs, and therefore the number"
    )


def test_the_hermetic_run_deselects_tests_that_cannot_run_here():
    script = VERIFY.read_text(encoding="utf-8")
    hermetic_block = script[script.find("HERMETIC coverage gate") :][:2000]
    assert 'not emulator and not chain' in hermetic_block, (
        "the deselection is what makes the number deterministic — a test that "
        "skips itself still counts as a test that did not cover its lines"
    )


def test_a_skipped_complete_gate_cannot_be_mistaken_for_a_pass():
    script = VERIFY.read_text(encoding="utf-8")
    assert "skip_gate \"complete coverage gate" in script
    # And the reason must say what has to be running.
    assert "no Firestore emulator on 127.0.0.1:8081" in script
