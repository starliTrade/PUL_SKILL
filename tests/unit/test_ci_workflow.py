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
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["game-server"]) if "run" in step
    )
    assert "--cov=api" in scripts, "CI runs pytest without the coverage ratchet"


def test_chain_tests_run_against_anvil(workflow: dict):
    scripts = "\n".join(
        step["run"] for step in _steps(workflow["jobs"]["contracts"]) if "run" in step
    )
    assert "start_anvil.sh" in scripts
    assert "-m chain" in scripts


def test_ruff_gate_exists(workflow: dict):
    assert "ruff" in _all_run_scripts(workflow)
