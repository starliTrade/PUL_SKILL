"""`docs/USER-TODO.md` tells a human to type commands, one step at a time.

A checklist that is wrong is worse than no checklist: the human types the
command, it fails, and every later step is suspect. These tests check the
document against the repository instead of trusting it — the scripts, the npm
scripts, the keeper flags, the chaos scenario names, the deploy environment
variables, the contract getters it calls, the counts it quotes, and the promise
that every phase has an exit condition.

The deploy-env check is deliberately repo-wide: it was written after
`GO-LIVE-RUNBOOK.md`, `MANUAL-CHECKLIST.md` and the remediation list all told the
operator to export `ORACLE_ADDRESS`/`TREASURY`, while `Deploy.s.sol` reads
`ORACLE_SIGNER_ADDRESS`/`TREASURY_ADDRESS`. Following the runbook would have
failed on deploy day with "environment variable not found".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RAW = (ROOT / "docs" / "USER-TODO.md").read_text(encoding="utf-8")

_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC = "٠١٢٣٤٥٦٧٨٩"


def _latin(text: str) -> str:
    out = []
    for ch in text:
        if ch in _PERSIAN:
            out.append(str(_PERSIAN.index(ch)))
        elif ch in _ARABIC:
            out.append(str(_ARABIC.index(ch)))
        else:
            out.append(ch)
    return "".join(out)


DOC = _latin(_RAW)
PACKAGE = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
KEEPER = (ROOT / "scripts" / "keeper.py").read_text(encoding="utf-8")
CHAOS = (ROOT / "scripts" / "chaos_suite.py").read_text(encoding="utf-8")
DEPLOY = (ROOT / "contracts" / "script" / "Deploy.s.sol").read_text(encoding="utf-8")
CONTRACT = (ROOT / "contracts" / "PulsarEscrow.sol").read_text(encoding="utf-8")


def _shell_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.S)


# --- 1. every command target exists ----------------------------------------
def test_every_script_it_names_exists() -> None:
    named = set(re.findall(r"(scripts/[\w./-]+\.(?:sh|py))", DOC))
    assert len(named) >= 7, f"the todo names only {len(named)} scripts"
    missing = sorted(n for n in named if not (ROOT / n).is_file())
    assert not missing, f"the todo tells a human to run scripts that do not exist: {missing}"


def test_every_document_and_env_example_it_names_exists() -> None:
    named = set(re.findall(r"`((?:docs/[\w./-]+\.md|\.env\.example))`", DOC))
    missing = sorted(n for n in named if not (ROOT / n).is_file())
    assert not missing, f"the todo cites files that do not exist: {missing}"


def test_every_npm_script_it_names_is_real() -> None:
    used = set(re.findall(r"npm run ([\w:-]+)", DOC))
    assert used, "the todo no longer runs any npm script"
    missing = sorted(s for s in used if s not in PACKAGE["scripts"])
    assert not missing, f"package.json has no script {missing}"


def test_the_keeper_flags_it_uses_are_real() -> None:
    for line in re.findall(r"keeper\.py([^\n`]*)", DOC):
        for opt in re.findall(r"--[\w-]+", line):
            assert f'"{opt}"' in KEEPER, f"keeper.py has no {opt}"


def test_the_chaos_scenario_names_are_real() -> None:
    line = re.search(r"chaos_suite\.py ([^\n]+)", DOC)
    assert line, "the todo no longer runs the chaos suite"
    names = re.findall(r"\b([a-z_]{3,})\b", line.group(1))
    named = [n for n in names if f'"{n}"' in CHAOS]
    assert len(named) >= 5, f"none of the chaos names in the todo exist: {line.group(1)}"


def test_the_contract_getters_it_calls_exist() -> None:
    for getter in re.findall(r'cast call \$ESCROW "(\w+)\(', DOC):
        assert re.search(rf"\b{getter}\b", CONTRACT), f"PulsarEscrow has no {getter}"


def test_the_pytest_markers_it_filters_on_are_registered() -> None:
    # `firestore` is a selection keyword the suite uses, not a declared marker in
    # pytest.ini; under `--strict-markers` the declared ones are what `-m` may
    # rely on without a warning, so pin those.
    cfg = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    declared = {"chain", "emulator"}
    used: set[str] = set()
    for expr in re.findall(r"-m \"?([\w ]+)\"?", DOC):
        if expr.strip().startswith("venv"):  # `python3 -m venv` is not a marker
            continue
        used |= {p for p in re.split(r"\s+or\s+|\s+and\s+|\s+", expr) if p}
    assert used & declared, "the todo filters on no declared marker"
    for marker in used & declared:
        assert marker in cfg, f"marker {marker} is not registered in pytest.ini"


# --- 2. the deploy trap, checked repo-wide --------------------------------
def _deploy_env_names() -> set[str]:
    return set(re.findall(r'env\w*\("([A-Z][A-Z0-9_]+)"', DEPLOY))


def test_the_deploy_env_check_has_something_to_check() -> None:
    names = _deploy_env_names()
    assert {"DEPLOYER_PRIVATE_KEY", "TREASURY_ADDRESS", "ORACLE_SIGNER_ADDRESS"} <= names


def test_no_document_teaches_the_wrong_deploy_environment() -> None:
    """Every `Deploy.s.sol` command in every doc must use the script's own names."""
    real = _deploy_env_names()
    # Shell variables a deploy command may legitimately define for itself.
    allowed = real | {"AMOY_RPC", "RPC_URL", "ETHERSCAN_API_KEY", "PRIVATE_KEY", "ESCROW"}
    offenders: list[str] = []
    for doc in [*sorted((ROOT / "docs").rglob("*.md")), ROOT / "README.md"]:
        text = doc.read_text(encoding="utf-8")
        for block in _shell_blocks(text):
            if "Deploy.s.sol" not in block:
                continue
            # A fenced block often holds several steps separated by blank lines
            # (deploy, then server env, then client env). Only the chunk that
            # contains the `forge script` command is a deploy command.
            for chunk in re.split(r"\n\s*\n", block):
                if "Deploy.s.sol" not in chunk:
                    continue
                for name in re.findall(r"(?:export\s+)?\b([A-Z][A-Z0-9_]{2,})=", chunk):
                    if name not in allowed:
                        offenders.append(f"{doc.relative_to(ROOT)}: {name}")
    assert not offenders, (
        "these deploy commands export variables Deploy.s.sol never reads — the "
        f"operator gets 'environment variable not found': {offenders}"
    )


def test_the_server_side_name_of_the_oracle_address_is_explained() -> None:
    # The server reads ORACLE_ADDRESS; the deploy script reads
    # ORACLE_SIGNER_ADDRESS. Two names, one address: the doc must say so.
    assert "ORACLE_ADDRESS" in DOC and "ORACLE_SIGNER_ADDRESS" in DOC
    assert "همان آدرس" in DOC


# --- 3. the numbers ------------------------------------------------------
def _readme_row(pattern: str) -> tuple[str, str] | None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(pattern, readme)
    return (m.group(1), m.group(2)) if m else None


def test_the_counts_it_quotes_are_the_ones_the_repo_reports() -> None:
    pytest_row = _readme_row(r"Server \(pytest\) \| (\d+) passed / (\d+) skipped with anvil[^|;]*running")
    assert pytest_row, "README lost its measured pytest row"
    assert f"**{pytest_row[0]} pass / {pytest_row[1]} skip**" in DOC

    vitest_row = _readme_row(r"Frontend \(vitest\) \| (\d+) tests, (\d+) files")
    assert vitest_row
    assert f"**{vitest_row[0]} تست / {vitest_row[1]} فایل**" in DOC

    forge_row = _readme_row(r"Contract \(forge, `default`\) \| (\d+) tests, (\d+) suites")
    assert forge_row, "README lost its measured forge row"
    assert f"**{forge_row[0]} تست / {forge_row[1]} سوئیت**" in DOC


def test_the_gate_count_is_the_script_s_gate_count() -> None:
    script = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    gates = len(re.findall(r'^\s*run_gate "', script, re.M))
    skips = len(re.findall(r"\s*skip_gate \"", script))
    assert "**22**" in DOC and gates == 22, f"verify.sh has {gates} gates"
    assert f"`skip_gate` خوردند ({skips} جای ممکن)" in DOC, f"verify.sh has {skips} skips"


def test_the_chain_and_emulator_counts_are_the_collected_counts() -> None:
    # Cheap proxy for `pytest --collect-only`: the markers exist and the numbers
    # quoted are the ones the other checklist pins (test_manual_checklist does the
    # expensive collection).
    assert "11 passed" in DOC
    assert "17 passed" in DOC
    other = _latin((ROOT / "docs" / "MANUAL-CHECKLIST.md").read_text(encoding="utf-8"))
    assert "17 passed" in other, "the two checklists disagree about the emulator count"


# --- 4. shape and honesty ------------------------------------------------
def test_every_phase_has_an_exit_condition() -> None:
    phases = re.split(r"\n## فاز ", DOC)[1:]
    assert len(phases) >= 11, f"the todo has {len(phases)} phases, expected 11+"
    for phase in phases:
        title = phase.splitlines()[0]
        assert "شرط عبور" in phase, f"phase {title!r} has no exit condition"


def test_it_is_granular_enough_to_be_a_checklist() -> None:
    boxes = re.findall(r"- \[[ x]\] \*\*(\d+)\.(\d+)\*\*", DOC)
    assert len(boxes) >= 60, f"only {len(boxes)} steps — this is not a step-by-step"
    # Numbering must restart per phase and increase: a skipped number hides a
    # deleted step.
    seen: dict[str, list[int]] = {}
    for phase, step in boxes:
        seen.setdefault(phase, []).append(int(step))
    for phase, steps in seen.items():
        assert steps == sorted(steps), f"phase {phase} has out-of-order steps"
        assert sorted(set(steps)) == steps, f"phase {phase} repeats a step number"


def test_it_does_not_pretend_a_never_run_step_passed() -> None:
    # Phase 11 is the scoreboard. The things this sandbox could not run must be
    # marked as such, not ticked.
    table = DOC.split("## فاز 11", 1)[1]
    for never_run in ("Firestore", "Playwright", "Amoy", "ممیزی"):
        row = [ln for ln in table.splitlines() if never_run in ln]
        assert row, f"the scoreboard lost its {never_run} row"
        assert any("❌" in ln for ln in row), f"{never_run} is no longer marked as not-run"
    assert "No-Go" in DOC


def test_the_money_rules_are_not_optional() -> None:
    # These are the three sentences that keep a launch from becoming a loss.
    assert "C-02c" in DOC
    assert "Safe" in DOC and "multisig" in DOC.lower()
    assert "KMS" in DOC
    assert "گزارش امضاشده" in DOC or "گزارش امضا شده" in DOC


def test_it_points_back_at_the_explanatory_checklist() -> None:
    assert "docs/MANUAL-CHECKLIST.md" in DOC
    other = (ROOT / "docs" / "MANUAL-CHECKLIST.md").read_text(encoding="utf-8")
    assert "docs/USER-TODO.md" in other, "the two checklists have drifted apart"
