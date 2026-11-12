"""`verify.sh` must not call a missing service a failure.

Found on 2026-10-25 while building the audit package and reading the evidence
file it produced. On a machine with no Foundry and no running API, four gates
came back ❌ FAIL:

* `refund after timeout (time travel)` — needs anvil and a deployed escrow;
* `alerting (healthy server must be quiet)` — needs a live `/api/health`;
* `runbook drill (the document matches the server)` — the same, and it died
  with a forty-line `urllib` traceback ending in `Connection refused`;
* `chaos suite` — printed "the API is not up", then exited **2**.

The summary then said "12 passed, 4 failed", and every one of those four
failures meant "this machine has no services". That is the exact confusion the
script was rewritten to remove (the chaos suite already SKIPs a missing emulator
with its reason), so the fix is the same shape: ask first, SKIP with the reason
AND the remedy, and let `--strict` refuse a skip in CI.

Two things are asserted here: the shell structure (each live gate is guarded, so
a future edit cannot quietly turn a SKIP back into a FAIL), and the chaos
suite's behaviour (it returns 0 and prints the machine-readable line rather than
exiting 2).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
CHAOS = ROOT / "scripts" / "chaos_suite.py"


def _block(gate_name: str) -> str:
    """The shell block that runs one gate: back to the previous section marker."""
    marker = f'"{gate_name}"'
    idx = VERIFY.index(marker)
    start = VERIFY.rfind("\n# ---", 0, idx)
    end = VERIFY.find("\n# ---", idx)
    return VERIFY[start if start != -1 else 0 : end if end != -1 else len(VERIFY)]


def test_the_helpers_exist_and_check_something_real() -> None:
    assert "api_reachable()" in VERIFY, "no precondition helper for the live API"
    assert "foundry_available()" in VERIFY, "no precondition helper for anvil/forge"
    assert "curl -fsS --max-time 3" in VERIFY, (
        "the reachability check must have a timeout: a gate that hangs on a "
        "black-holed address is the failure mode it exists to prevent"
    )
    # The URL is configurable, because CI does not always bind :8000.
    assert "PULSAR_API_HEALTH_URL" in VERIFY


@pytest.mark.parametrize(
    "gate, helper",
    [
        ("refund after timeout (time travel)", "foundry_available"),
        ("alerting (healthy server must be quiet)", "api_reachable"),
        ("runbook drill (the document matches the server)", "api_reachable"),
    ],
)
def test_each_live_gate_is_guarded_and_skips_with_a_remedy(gate: str, helper: str) -> None:
    block = _block(gate)
    run_at = block.index(f'run_gate "{gate}"')
    guard_at = block.index(f"! {helper}")
    assert guard_at < run_at, f"{gate} runs before it checks {helper}"
    assert "skip_gate" in block[guard_at:run_at], (
        f"{gate} checks {helper} and then runs anyway instead of skipping"
    )
    skipped = block[block.index("skip_gate", guard_at) : run_at]
    assert "start_" in skipped or "install" in skipped, (
        f"{gate}'s skip reason names no remedy, so the reader has to go and find one"
    )


def test_the_chaos_gate_still_uses_the_skip_aware_wrapper() -> None:
    # The wrapper turns the suite's machine-readable SKIPPED line into a gate
    # SKIP. A plain run_gate here would count a fully-skipped suite as a pass.
    assert "run_gate_skippable()" in VERIFY
    # The `skip_gate` line in the same if/else names the missing-script case and
    # is correctly NOT a run; assert on the RUN line only.
    run_lines = [
        ln
        for ln in VERIFY.splitlines()
        if "chaos suite (rpc/firestore" in ln and "skip_gate" not in ln
    ]
    assert run_lines and all("run_gate_skippable" in ln for ln in run_lines)


def test_a_missing_api_is_a_skip_not_a_failure() -> None:
    """The suite's own contract, executed rather than grepped."""
    # `api_up` is checked at the top of main(); the emulator may well be absent
    # on this machine, which is the other skip path and is covered elsewhere.
    code = (
        "import sys; sys.path.insert(0, 'scripts'); import chaos_suite as c;"
        "c.api_up = lambda: False;"
        "raise SystemExit(c.main([]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"a missing API made the chaos suite exit {result.returncode} — "
        f"'not exercised' is being reported as 'failed':\n{result.stdout}{result.stderr}"
    )
    assert "SKIPPED (environment)" in result.stdout, (
        "the machine-readable line is what lets verify.sh report SKIP; without "
        "it the gate looks like a pass"
    )
    assert "start_e2e_stack.sh" in result.stdout, "the skip does not name the remedy"


def test_strict_still_refuses_a_skip() -> None:
    # `--strict` is the CI posture: every skip becomes a failure, so a machine
    # that is missing a service cannot report green.
    wrapper = VERIFY.split("run_gate_skippable()", 1)[1].split("skip_gate()", 1)[0]
    assert "STRICT" in wrapper
    assert re.search(r'if \[\[ "\$STRICT" == "1" \]\]', wrapper), (
        "the wrapper no longer escalates a skip under --strict"
    )
