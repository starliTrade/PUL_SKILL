"""The health probe must ANSWER, even when the server is misconfigured.

Audit 2026-10-13 (found by the phase-10 load run): `/api/health` called
`oracle_address()` unguarded, and `load_signer()` raises when
ORACLE_PRIVATE_KEY is absent — so the probe returned 500. An orchestrator
reads that as a crashed container and restarts it, turning "the oracle key is
missing" into a crash loop instead of the one fact the operator needs.

This runs the server in a SUBPROCESS on purpose: importing `main` in-process
and then removing it from `sys.modules` to test a second configuration corrupts
every other test in the session (it did — 16 of them). A child interpreter has
its own module table, so the isolation is real rather than hopeful.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "api"))

_PROBE = textwrap.dedent(
    """
    import json, sys
    from fastapi.testclient import TestClient
    import main
    res = TestClient(main.app).get("/api/health")
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    print(json.dumps({"status": res.status_code, "body": body}))
    """
)


def _probe(env_overrides: dict[str, str | None]) -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PULSAR_ENV": "dev",
        "ORACLE_SIGNING_SECRET": "0x" + "11" * 32,
    }
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"the probe crashed:\n{proc.stderr[-2000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_health_answers_when_the_oracle_key_is_missing():
    result = _probe({"ORACLE_PRIVATE_KEY": None})

    assert result["status"] == 200, (
        f"the health probe returned {result['status']} for a misconfigured server — "
        "an orchestrator would restart the container instead of reporting the cause"
    )
    body = result["body"]
    assert body["ok"] is True
    # The misconfiguration is REPORTED rather than raised.
    assert body["oracleAddress"] is None
    assert body["oracleConfigured"] is False


def test_health_reports_the_oracle_address_when_it_is_configured():
    # A well-known anvil key — never a real one.
    key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    result = _probe({"ORACLE_PRIVATE_KEY": key})

    assert result["status"] == 200
    body = result["body"]
    assert body["oracleConfigured"] is True
    assert body["oracleAddress"] == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
