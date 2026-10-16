"""The CI workflow is itself a thing that can silently break (plan item 0.13).

CI-1 was exactly this: the contract job looked configured but never compiled,
so 21 tests never ran and nobody noticed. A malformed workflow file is worse —
GitHub reports nothing and no job runs at all. These tests treat
`.github/workflows/ci.yml` as a contract and assert the properties that matter.

They also caught a real bug while being written: `- name: Chain tests (real EVM:
create -> ...)` is invalid YAML because of the unquoted colon, and the whole
workflow failed to parse.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps(job: dict) -> list[dict]:
    return job.get("steps", [])


def _all_run_scripts(workflow: dict) -> str:
    return "\n".join(
        step["run"] for job in workflow["jobs"].values() for step in _steps(job) if "run" in step
    )


def test_workflow_parses(workflow: dict):
    assert "jobs" in workflow and workflow["jobs"], "the workflow has no jobs"


def test_expected_jobs_exist(workflow: dict):
    assert {"frontend", "game-server", "contracts"} <= set(workflow["jobs"])


def test_every_run_step_has_a_body(workflow: dict):
    for job_name, job in workflow["jobs"].items():
        for index, step in enumerate(_steps(job)):
            if "run" in step:
                assert str(step["run"]).strip(), f"{job_name} step {index} has an empty run"


def test_every_step_has_a_name_or_a_use(workflow: dict):
    for job_name, job in workflow["jobs"].items():
        for index, step in enumerate(_steps(job)):
            assert "name" in step or "uses" in step, f"{job_name} step {index} is unlabelled"


# --- CI-1 regression guards ---------------------------------------------------
def test_contract_job_installs_openzeppelin(workflow: dict):
    """CI-1: MockUSDT imports ERC20 from OpenZeppelin.

    Without this clone `forge test` cannot compile, so the 21 contract tests
    silently never run — the exact state this repository shipped in.
    """
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["contracts"]) if "run" in step
    )
    assert "openzeppelin-contracts" in scripts, (
        "the contracts job does not install OpenZeppelin — forge test will fail "
        "to compile and the contract suite will silently not run (CI-1)"
    )
    assert "forge-std" in scripts


def test_contract_job_asserts_tests_actually_ran(workflow: dict):
    """A green `forge test` that executed zero tests must not pass."""
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["contracts"]) if "run" in step
    )
    assert "test_results" in scripts, "no guard counts the executed contract tests"


def test_contract_deps_are_pinned(workflow: dict):
    """Floating test dependencies make a green run unreproducible."""
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["contracts"]) if "run" in step
    )
    assert "--branch v" in scripts, "forge-std / OpenZeppelin are cloned unpinned"


def test_foundry_toolchain_is_pinned(workflow: dict):
    for step in _steps(workflow["jobs"]["contracts"]):
        if str(step.get("uses", "")).startswith("foundry-rs/foundry-toolchain"):
            version = str(step.get("with", {}).get("version", ""))
            assert version.startswith("v"), f"Foundry version is not pinned: {version!r}"
            return
    pytest.fail("the contracts job does not install Foundry")


# --- gates that must exist ----------------------------------------------------
def test_firestore_emulator_is_started(workflow: dict):
    """Without it, test_firestore_integration.py skips and C1/H3/H4 stay hidden."""
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["game-server"]) if "run" in step
    )
    assert "firestore-emulator" in scripts
    assert "FIRESTORE_EMULATOR_HOST" in str(workflow["jobs"]["game-server"])


def test_pytest_runs_with_the_coverage_ratchet(workflow: dict):
    """The ratchet is enforced by `coverage report` over the whole suite.

    Audit HIGH-8 changed HOW it is measured (one session over pytest + the
    legacy suites, matching `scripts/verify.sh`) — not whether.
    """
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["game-server"]) if "run" in step
    )
    assert "coverage report" in scripts, "CI runs pytest without the coverage ratchet"


def test_chain_tests_run_against_anvil(workflow: dict):
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["contracts"]) if "run" in step
    )
    assert "start_anvil.sh" in scripts
    assert "-m chain" in scripts


def test_ruff_gate_exists(workflow: dict):
    assert "ruff" in _all_run_scripts(workflow)


def test_game_server_install_step_cannot_fail_before_any_test(workflow: dict):
    """The install step must not install a package that does not exist.

    It used to run `sudo apt-get install -y python3-sqlite3`. That package does
    not exist on Ubuntu noble, so the step exited 100 and the ENTIRE
    game-server job — ruff, pytest, the coverage ratchet, the emulator suites —
    never ran. CI was red for reasons unrelated to the code, and every
    server-side gate was silently absent.

    sqlite3 ships with the setup-python distribution (it backs the
    google-cloud-firestore STDLib fallback), so the job must ASSERT it is
    importable instead of installing a package that is not there.
    """
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["game-server"]) if "run" in step
    )
    assert "python3-sqlite3" not in scripts, (
        "the game-server job installs python3-sqlite3, which does not exist on "
        "Ubuntu noble — the install step fails before any test runs"
    )
    assert "import sqlite3" in scripts, (
        "the game-server job must verify sqlite3 is importable — the Firestore "
        "STDLib fallback depends on it, and a silent fallback to the memory "
        "store is the blind spot that hid C1/H3/H4"
    )


# --- audit 2026-10-13: the gates must be the SAME gates -----------------------


def _job_scripts(workflow: dict, job: str) -> str:
    return "\n".join(step["run"] for step in _steps(workflow["jobs"][job]) if "run" in step)


def test_ci_measures_coverage_the_same_way_verify_does(workflow: dict):
    """Audit HIGH-8: a green `verify` must imply a green CI.

    CI measured `pytest --cov=api` alone (79.09% against a 79.0 floor) while
    `scripts/verify.sh` measured pytest PLUS the legacy suites in one session
    (81%). The two gates disagreed, so CI could fail on a change verify passed.
    Both must now use one coverage session: `coverage run` then `--append`.
    """
    scripts = _job_scripts(workflow, "game-server")
    assert "coverage run --source=api -m pytest" in scripts, (
        "CI does not run pytest under a coverage session"
    )
    assert scripts.count("coverage run --append --source=api") >= 3, (
        "the legacy suites are not appended to the same coverage session"
    )
    assert "coverage report" in scripts, "CI never enforces the ratchet"
    # ...and it must NOT use the pytest-cov shortcut that measures a different set.
    assert "--cov=api" not in scripts, (
        "CI still measures pytest alone with pytest-cov — a different gate from verify.sh"
    )


def test_ci_asserts_the_server_suite_actually_ran(workflow: dict):
    """A suite that collects nothing must not look green."""
    scripts = _job_scripts(workflow, "game-server")
    assert "collect-only" in scripts, (
        "the game-server job has no 'the suite actually ran' guard"
    )


def test_the_contracts_job_uses_the_ci_profile(workflow: dict):
    """`[profile.ci]` in foundry.toml was dead config — nothing selected it."""
    for step in _steps(workflow["jobs"]["contracts"]):
        if "forge test" in str(step.get("run", "")):
            assert str(step.get("env", {}).get("FOUNDRY_PROFILE", "")) == "ci", (
                "the contracts job runs forge test without FOUNDRY_PROFILE=ci, so "
                "the larger fuzz/invariant budgets never run"
            )
            return
    pytest.fail("the contracts job does not run forge test")


def test_the_contract_test_floor_is_near_the_real_count(workflow: dict):
    """A floor far below the real count only catches 'zero tests'."""
    scripts = _job_scripts(workflow, "contracts")
    match = re.search(r'test "\$ran" -ge (\d+)', scripts)
    assert match, "no contract-test floor"
    assert int(match.group(1)) >= 75, (
        f"the contract-test floor is {match.group(1)} while the suite has ~81 tests"
    )


def test_ci_runs_the_same_gates_verify_does() -> None:
    """The parity claim, asserted instead of assumed.

    Audit 2026-10-16: `verify.sh` opened with "CI runs the same gates (see
    .github/workflows/ci.yml), so 'green locally' and 'green in CI' mean the same
    thing" — and it was FALSE. chaos, the runbook drill, alerting, the refund
    time-travel suite, the live-stack ranked flow and both probes ran nowhere in
    CI, so every Phase-A fix was unprotected: breaking `start_anvil.sh` would
    have left CI green.

    A claim in a comment cannot fail. This can: it reads both files and fails if
    CI stops running the heavy gates.
    """
    ci = WORKFLOW.read_text(encoding="utf-8")
    verify = (WORKFLOW.parents[2] / "scripts" / "verify.sh").read_text(encoding="utf-8")

    # The heavy gates verify.sh runs, and the script each one invokes.
    heavy = ["chaos_suite.py", "runbook_drill.py", "check_alerts.py", "test_refund_after_timeout.py", "test_ranked_flow_e2e.py"]
    for name in heavy:
        assert name in verify, f"verify.sh no longer runs {name} — the parity test is stale"

    # CI does not have to name each one; it must run the SAME ENTRY POINT, which
    # is the only way the two cannot drift.
    assert "bash scripts/verify.sh" in ci, (
        "CI does not run scripts/verify.sh, so the gates verify.sh runs are not "
        "protected. Either add the verify-gates job back, or delete the parity "
        "claim from verify.sh — do not leave the comment claiming something false."
    )
