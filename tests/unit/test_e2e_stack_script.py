"""The E2E launcher must be runnable, and its safety check must actually run.

Found while auditing L-04 (the README claimed Playwright always skips). It was
not skipping — it was failing to start, twice over:

  1. `exit 1# --- 0. the manifest and the CHAIN must agree` — one lost newline
     turned the rest of the file into a comment. The script exited with
     "1#: numeric argument required" (status 2) on every failed start, and the
     stale-manifest guard it contained had NEVER executed. That guard exists to
     stop the exact failure it was silently not preventing: an API pointed at an
     escrow address with no code, which reports `escrowConfigured: true` and then
     fails every duel with a message that reads like a server bug.
  2. The stack launched the API with `ORACLE_SIGNER=local` and no explicit
     opt-in, so H-07 (correctly) refused to boot. A test harness whose only
     option is to disable the production checks defeats its own purpose.

These tests are hermetic: no anvil, no emulator, no API. The guard is exercised
with an unreachable RPC, which is also the "manifest is stale" case.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "start_e2e_stack.sh"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — a fixed script path, no shell
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
        timeout=60,
    )


def _tmp_manifest(tmp_path: Path, **over) -> Path:
    data = {
        "escrow": "0x" + "de" * 20,
        "rpcUrl": "http://127.0.0.1:8545",
        "chainId": 31337,
        "oracleKey": "0x" + "11" * 32,
    }
    data.update(over)
    path = tmp_path / "local.json"
    path.write_text(json.dumps(data))
    return path


def test_the_script_parses() -> None:
    """`bash -n` would have caught the lost newline at the source."""
    proc = subprocess.run(  # noqa: S603
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


def test_no_line_swallows_the_rest_of_the_file() -> None:
    """The exact corruption: `exit 1` immediately followed by a comment marker."""
    for line in SCRIPT.read_text().splitlines():
        assert not line.startswith("exit 1#"), (
            "a comment was glued onto an exit status — the rest of the file is dead code"
        )


def test_a_stale_manifest_is_refused_before_the_api_starts(tmp_path: Path) -> None:
    """No contract at the manifest's escrow (here: no reachable chain at all).

    The old code started uvicorn first and only then (never) checked.
    """
    manifest = _tmp_manifest(tmp_path)
    proc = _run(
        {
            "PULSAR_E2E_MANIFEST": str(manifest),
            "PULSAR_ANVIL_URL": "http://127.0.0.1:1",
            "PULSAR_E2E_API_PORT": "8791",
            "PULSAR_API_PORT": "8791",
        }
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "REFUSING TO START" in out
    assert "start_anvil.sh" in out
    # And it refused BEFORE trying to boot: no uvicorn was launched by this run.
    assert "E2E API up" not in out


def test_a_missing_manifest_is_a_clear_error(tmp_path: Path) -> None:
    proc = _run(
        {
            "PULSAR_E2E_MANIFEST": str(tmp_path / "nope.json"),
            "PULSAR_E2E_API_PORT": "8792",
        }
    )
    assert proc.returncode == 1
    assert "no deployment manifest" in proc.stdout + proc.stderr


def test_the_local_signer_is_accepted_explicitly_not_by_disabling_production_gates() -> None:
    lines = [ln.strip() for ln in SCRIPT.read_text().splitlines()]
    assert any(ln.startswith("PULSAR_ALLOW_LOCAL_SIGNER=1") for ln in lines)
    # PULSAR_ENV=dev turns off the fail-closed checks this suite exists to test —
    # it may be MENTIONED in a comment, never assigned.
    assert not any(ln.startswith("PULSAR_ENV=") for ln in lines)
