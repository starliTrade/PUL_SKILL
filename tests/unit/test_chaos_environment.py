"""The chaos suite must not call "not exercised" a defect.

The suite has five scenarios and several need a service: the Firestore emulator
(a JRE) and a second uvicorn port. On a machine without those, the first version
printed

    chaos summary: 20 passed, 4 failed
      FAILED: the emulator is up before the scenario
      FAILED: the emulator recovers
      FAILED: both replicas answer an authenticated read
      FAILED: replica_split completed — TimeoutExpired: ... timed out after 15 seconds

Four red lines whose only meaning was "Java is not installed" — and the fourth was
the harness's own shutdown time-out reported as if the server had hung. A tool
that cannot tell "not exercised" from "wrong" teaches its reader to ignore it.

These tests pin the separation, and they fail against the old code: the skip list
did not exist, and `scenario_firestore_kill` recorded a FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import chaos_suite  # noqa: E402  (needs the scripts/ path)

SOURCE = (ROOT / "scripts" / "chaos_suite.py").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_buckets():
    chaos_suite.PASS.clear()
    chaos_suite.FAIL.clear()
    chaos_suite.SKIP.clear()
    yield
    chaos_suite.PASS.clear()
    chaos_suite.FAIL.clear()
    chaos_suite.SKIP.clear()


@pytest.fixture()
def no_emulator(monkeypatch):
    monkeypatch.setattr(chaos_suite, "emulator_up", lambda: False)
    monkeypatch.setattr(chaos_suite, "start_emulator", lambda: None)
    # Any attempt to launch a process would be a bug: with no emulator the
    # replica scenario has nothing to test.
    monkeypatch.setattr(
        chaos_suite.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("a process was launched without the emulator"),
    )


def test_a_missing_emulator_is_a_skip_not_a_failure(no_emulator) -> None:
    chaos_suite.scenario_firestore_kill()
    assert chaos_suite.FAIL == [], "a missing service was reported as a defect"
    assert len(chaos_suite.SKIP) == 1
    assert "firestore_kill" in chaos_suite.SKIP[0]
    assert "emulator" in chaos_suite.SKIP[0]
    assert chaos_suite.PASS == [], "nothing was actually exercised"
    # And it says how to fix it, on the same line.
    assert "start_emulator.sh" in chaos_suite.SKIP[0]


def test_replica_split_skips_before_it_launches_anything(no_emulator) -> None:
    chaos_suite.scenario_replica_split()
    assert chaos_suite.FAIL == []
    assert len(chaos_suite.SKIP) == 1
    assert "replica_split" in chaos_suite.SKIP[0]


def test_the_skip_line_is_machine_readable(monkeypatch, capsys) -> None:
    """`verify.sh` greps for this exact prefix; prose would not be enough."""
    monkeypatch.setattr(chaos_suite, "api_up", lambda: True)
    monkeypatch.setattr(chaos_suite, "SCENARIOS", {"firestore_kill": chaos_suite.scenario_firestore_kill})
    monkeypatch.setattr(chaos_suite, "emulator_up", lambda: False)
    monkeypatch.setattr(chaos_suite, "start_emulator", lambda: None)

    assert chaos_suite.main([]) == 0, "an environment skip must not fail the suite"
    out = capsys.readouterr().out
    assert "\nSKIPPED (environment): 1 scenario(s)" in out
    assert "skipped (environment)" in out.splitlines()[-4] or "skipped (environment)" in out


def test_a_real_failure_still_fails_the_suite(monkeypatch, capsys) -> None:
    """The other half of the contract: a broken assertion must stay red."""

    def broken() -> None:
        chaos_suite.check("the server answers", False, "status=0")

    monkeypatch.setattr(chaos_suite, "api_up", lambda: True)
    monkeypatch.setattr(chaos_suite, "SCENARIOS", {"broken": broken})
    assert chaos_suite.main([]) == 1
    assert "FAILED: the server answers" in capsys.readouterr().out


def test_a_scenario_that_raises_is_reported_with_its_name(monkeypatch, capsys) -> None:
    def explodes() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(chaos_suite, "api_up", lambda: True)
    monkeypatch.setattr(chaos_suite, "SCENARIOS", {"explodes": explodes})
    assert chaos_suite.main([]) == 1
    assert "explodes completed" in capsys.readouterr().out


def test_no_scenario_discards_the_second_replica_s_output() -> None:
    # The old code sent stdout/stderr to DEVNULL, so `b=0` was all the operator got.
    assert "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" not in SOURCE
    assert "replica_reason()" in SOURCE


def test_the_replica_shutdown_cannot_hang_the_scenario() -> None:
    # `proc.wait(timeout=15)` alone let a stuck child turn into TimeoutExpired,
    # which main() then reported as "replica_split completed — TimeoutExpired".
    body = SOURCE.split("def scenario_replica_split", 1)[1].split("\ndef ", 1)[0]
    assert "SIGKILL" in body
    assert body.count("TimeoutExpired") >= 2


def test_verify_sh_reports_the_gate_as_a_skip_not_a_pass() -> None:
    assert "run_gate_skippable()" in VERIFY
    assert "grep -q '^SKIPPED (environment)'" in VERIFY
    chaos_gate = [ln for ln in VERIFY.splitlines() if "chaos suite (rpc/firestore/replica/delay/soak)" in ln]
    assert chaos_gate, "the chaos gate disappeared from verify.sh"
    assert any("run_gate_skippable" in ln for ln in chaos_gate), (
        "the chaos gate is back to a plain run_gate, so a skipped scenario would "
        "be counted as a pass"
    )
    # And --strict must still refuse to accept it.
    wrapper = VERIFY.split("run_gate_skippable()", 1)[1].split("skip_gate()", 1)[0]
    assert "STRICT" in wrapper and "a skipped scenario is a failure" in wrapper
