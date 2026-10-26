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


def test_the_verify_gates_job_installs_dependencies_that_exist(workflow: dict) -> None:
    """This job exists to prove "CI runs the same gates a human runs".

    It read `requirements.txt` from the repository ROOT. The requirements live in
    `api/`, so the step failed in eight seconds and — because it is not
    `|| true` — every later step was skipped: frontend deps, Foundry, Playwright,
    anvil, and `bash scripts/verify.sh`. A job that never reaches its gate shows
    the same red X as a gate that failed, which is how "verify-gates is red" was
    true for the whole life of the job while the gate itself had never run.
    """
    scripts = _job_scripts(workflow, "verify-gates")
    assert "-r api/requirements-dev.txt" in scripts, (
        "the verify-gates job must install the server deps from api/"
    )
    assert "-r requirements.txt" not in scripts, (
        "there is no requirements.txt at the repository root; this step fails "
        "before verify.sh is ever reached"
    )


def test_the_verify_gates_job_installs_the_solidity_libraries(workflow: dict) -> None:
    """`start_anvil.sh` compiles PulsarEscrow, which imports OpenZeppelin.

    The repo does not vendor `lib/` (deliberately), so a clean runner must clone
    it. verify-gates did not, and the run stopped at "Deploy the escrow to a
    local anvil" — one step before the gate it exists to run.
    """
    steps = _steps(workflow["jobs"]["verify-gates"])
    names = [step.get("name", "") for step in steps]
    lib_at = next(i for i, n in enumerate(names) if "Solidity test dependencies" in n)
    anvil_at = next(i for i, n in enumerate(names) if n == "Deploy the escrow to a local anvil")
    assert lib_at < anvil_at, "the libraries are installed after the deploy that needs them"
    install = steps[lib_at]["run"]
    assert "openzeppelin-contracts" in install and "forge-std" in install
    assert "test -f lib/forge-std/src/Test.sol" in install, (
        "a clone that silently produced nothing must fail here, not three steps later"
    )


def test_a_failing_test_step_reports_the_failing_ids(workflow: dict) -> None:
    """A red X with "exit code 1" cannot be attributed.

    The server-test step produces thousands of lines of output; the failing test
    ids are in there and nowhere else. The step now re-emits them as check
    annotations, which the API returns as structured data — that is the
    difference between "CI is red" and "these four tests failed".
    """
    scripts = _job_scripts(workflow, "game-server")
    assert "::error::" in scripts, "the test step does not surface failures as annotations"
    assert "PIPESTATUS" in scripts, (
        "the step must exit with pytest's status, not tee's — otherwise a failing "
        "suite reports success"
    )


def test_a_failing_gate_lists_the_gate_that_failed(workflow: dict) -> None:
    """A red build must say WHICH of the 22 gates failed.

    `::error::` annotations were tried first and do not survive: the check-run
    API returns only GitHub's generic "Process completed with exit code 1" for a
    failing step. The job summary does survive — it comes back as
    `output.summary` — so that is the channel, and this test pins it.
    """
    steps = _steps(workflow["jobs"]["verify-gates"])
    summaries = [s for s in steps if s.get("if") == "failure()" and "$GITHUB_STEP_SUMMARY" in s.get("run", "")]
    assert summaries, "a failing gate run leaves no evidence outside the unreadable log"
    dump = "\n".join(s["run"] for s in summaries)
    assert "/tmp/verify-run.log" in dump, "the summary does not contain verify.sh's own output"
    assert "VERIFY SUMMARY" in dump, "the summary does not include which gates failed"


def test_a_failing_server_suite_leaves_its_evidence_in_the_summary(workflow: dict) -> None:
    steps = _steps(workflow["jobs"]["game-server"])
    summaries = [s for s in steps if s.get("if") == "failure()" and "$GITHUB_STEP_SUMMARY" in s.get("run", "")]
    assert summaries, "a failing server suite leaves no evidence outside the unreadable log"
    assert any("/tmp/pytest.log" in s["run"] for s in summaries)


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
    # 2026-10-23: the suite is 104 tests (measured, FOUNDRY_PROFILE=ci). The
    # floor guards against a regression that deletes tests, so it must sit just
    # under the real number — 75 allowed 29 tests to vanish without a failure.
    assert int(match.group(1)) >= 100, (
        f"the contract-test floor is {match.group(1)} while the suite has 104 tests"
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
