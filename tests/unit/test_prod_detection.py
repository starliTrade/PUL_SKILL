"""Audit M-08 (2026-10-22) — a `dev` label must not survive on a real platform.

The opt-out from every production safeguard is one word: `PULSAR_ENV=dev`, which
is what `.env.example` ships. The failure mode that actually happens is copying
that file onto a host: the SIWE domain check, the CORS allow-list, the signer
policy and the required-env gate all switch off, and nothing complains.

The check runs at import time, so these tests boot a subprocess rather than
reload the module — reloading `main` in-process would also re-register routes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BASE_ENV = {
    "ALLOWED_DOMAIN": "pulsar.test",
    "CORS_ALLOW_ORIGINS": "https://pulsar.test",
    "ESCROW_ADDRESS": "0x" + "ab" * 20,
    "ESCROW_RPC_URL": "http://127.0.0.1:8545",
    "ORACLE_SIGNING_SECRET": "s" * 32,
    "ORACLE_CHAIN_ID": "80002",
    # The durable-store check would otherwise complain before we assert anything.
    "PULSAR_MATCH_STORE": "memory",
}


def _boot(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        # Start from a clean slate: the test runner's own env must not leak in.
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PULSAR_", "K_SERVICE", "K_REVISION", "RENDER", "FLY_", "DYNO", "NODE_ENV"))
    }
    env.update(BASE_ENV)
    env.update(overrides)
    script = "import sys; sys.path.insert(0,'api'); import main; print('BOOTED', main._prod_like)"
    return subprocess.run(  # noqa: S603 - fixed command, no shell
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_dev_label_on_cloud_run_refuses_to_start():
    proc = _boot(PULSAR_ENV="dev", K_SERVICE="pulsar-api")
    assert proc.returncode != 0
    assert "M-08" in proc.stderr
    assert "K_SERVICE" in proc.stderr


def test_every_platform_marker_is_recognised():
    for marker in ("K_SERVICE", "RENDER", "FLY_MACHINE_ID", "DYNO"):
        proc = _boot(PULSAR_ENV="dev", **{marker: "1"})
        assert proc.returncode != 0, f"{marker} did not trip the dev-on-platform check"
        assert marker in proc.stderr


def test_node_env_production_counts_as_deployed():
    proc = _boot(PULSAR_ENV="dev", NODE_ENV="production")
    assert proc.returncode != 0
    assert "NODE_ENV" in proc.stderr


def test_a_plain_local_run_still_works():
    proc = _boot(PULSAR_ENV="dev")
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "BOOTED False" in proc.stdout


def test_the_staging_escape_hatch_is_explicit_and_narrow():
    proc = _boot(PULSAR_ENV="dev", K_SERVICE="pulsar-api", PULSAR_ALLOW_DEV_ON_PLATFORM="1")
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "BOOTED False" in proc.stdout


def test_a_production_label_is_still_prod_like_on_a_platform():
    """A real deployment must be prod-like, and then the H-07 signer gate applies."""
    proc = _boot(PULSAR_ENV="production", K_SERVICE="pulsar-api")
    assert proc.returncode != 0
    assert "ORACLE_SIGNER" in proc.stderr


def test_the_escape_hatch_is_documented_where_people_copy_from():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "PULSAR_ALLOW_DEV_ON_PLATFORM" in example
    assert "REFUSES to start" in example
