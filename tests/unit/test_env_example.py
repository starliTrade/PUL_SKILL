"""6.7 — `.env.example` must name every variable the code actually reads.

The file it replaces listed six variables, four of which nothing reads
(`DEFAULT_NETWORK`, `FIREBASE_API_KEY`, `ORACLE_WALLET_ADDRESS`,
`TREASURY_WALLET_ADDRESS` — the real names are VITE_-prefixed). An operator
following it would have configured a deployment that ignores everything they
set. This test is the guard against that drift coming back.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

# Read by the local rehearsal script (`scripts/rehearse_amoy_e2e.py`), not part
# of a deployment's configuration.
SCRIPT_ONLY = {
    "REHEARSE_SERVER",
    "REHEARSE_RPC",
    # The rehearsal driver's Host header. Overridable because a LOCAL rehearsal
    # runs against an API whose TrustedHost allowlist is 127.0.0.1, not Amoy.
    "REHEARSE_DOMAIN",
    "STAKE_USDT",
    "MOCK_USDT",
    "PLAYER1_KEY",
    "PLAYER2_KEY",
    # The chaos suite passes PATH through to the anvil subprocess; it is the
    # shell's variable, not the server's configuration.
    "PATH",
    # `scripts/migrate_firestore.py` (plan item 6.11) points the Firestore client
    # at the emulator. These are the Google client library's own variables — the
    # server reads them too, but only in a test/emulator context, and setting
    # them in production would be wrong.
    "FIRESTORE_EMULATOR_HOST",
    "GCLOUD_PROJECT",
    # `scripts/check_alerts.py` (plan item 11.2) — the alerting check's own
    # configuration, not the server's. The server never reads either.
    "PULSAR_ALERT_URL",
    "PULSAR_ALERT_WEBHOOK",
    "PULSAR_DRILL_API",
    # The drill and the live-preview script name the anvil port so they can
    # check the dependency directly rather than trusting a health endpoint.
    "PULSAR_ANVIL_PORT",
}

# Public configuration, not secrets — a chain id is in every RPC request.
PUBLIC_VALUES = {"VITE_CHAIN_ID", "ORACLE_CHAIN_ID", "PULSAR_ENV"}


def _documented() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", EXAMPLE, re.M))


def _server_vars() -> set[str]:
    found: set[str] = set()
    for path in list((ROOT / "api").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"os\.environ(?:\.get)?\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']", src))
        found |= set(re.findall(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]", src))
    return found


def _client_vars() -> set[str]:
    """Only REAL reads — `import.meta.env.X`, `env.X`, `env['X']`.

    A plain grep for `VITE_` also matches the comments that mention variable
    names, which would make this test assert against prose.
    """
    found: set[str] = set()
    for path in list((ROOT / "src").rglob("*.ts")) + list((ROOT / "src").rglob("*.tsx")):
        src = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"env\??\.(VITE_[A-Z0-9_]+)", src))
        found |= set(re.findall(r"env\??\[\s*[\"'](VITE_[A-Z0-9_]+)[\"']\s*\]", src))
    return found


def test_the_example_file_is_not_empty() -> None:
    assert len(_documented()) >= 25, "the reference file is suspiciously thin"


def test_every_server_variable_is_documented() -> None:
    missing = _server_vars() - _documented() - SCRIPT_ONLY
    assert not missing, (
        f"read by the server but absent from .env.example: {sorted(missing)}"
    )


def test_every_client_variable_is_documented() -> None:
    missing = _client_vars() - _documented()
    assert not missing, (
        f"read by the client but absent from .env.example: {sorted(missing)}"
    )


def test_the_example_file_carries_no_real_secrets() -> None:
    """Every assignment must be empty — this file is committed."""
    for line in EXAMPLE.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in PUBLIC_VALUES:
            continue
        assert value.strip() == "", f"{key} carries a value in a committed file"
