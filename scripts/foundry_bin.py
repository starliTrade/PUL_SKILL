"""Locate the Foundry binaries, wherever they were installed (audit H-19).

Four places in this repository — the ranked-flow E2E, the refund time-travel
test, `scripts/chaos_suite.py` and `scripts/runbook_drill.py` — called
`/root/workspace/.foundry/bin/cast` by absolute path. That path exists in the
sandbox this project was audited in, and nowhere else. On a developer machine
(`~/.foundry/bin`), in CI (the official Foundry installer) or under nix, the
gate failed with `FileNotFoundError` — which is indistinguishable, from the
outside, from "the feature is broken".

`scripts/start_anvil.sh` and `scripts/verify.sh` already searched a list of
candidates. This module is the same rule in Python, so the tests and scripts
cannot drift from it.

Precedence, in this order:
    1. `PULSAR_CAST` / `PULSAR_FORGE` (an explicit override, for CI caches)
    2. whatever is on PATH
    3. `~/.foundry/bin` (the official installer)
    4. the legacy sandbox path, kept last so existing runs keep working
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_FALLBACK_DIRS = (
    Path.home() / ".foundry" / "bin",
    Path("/root/workspace/.foundry/bin"),
)


class FoundryMissing(RuntimeError):
    """The binary is not installed — say so, with the one-line fix."""


def bin_path(name: str) -> str:
    """Absolute path to a Foundry binary, or raise `FoundryMissing`."""
    override = os.environ.get(f"PULSAR_{name.upper()}", "").strip()
    if override:
        if not os.access(override, os.X_OK):
            raise FoundryMissing(
                f"PULSAR_{name.upper()} points at {override}, which is not executable"
            )
        return override

    found = shutil.which(name)
    if found:
        return found

    for directory in _FALLBACK_DIRS:
        candidate = directory / name
        if os.access(candidate, os.X_OK):
            return str(candidate)

    raise FoundryMissing(
        f"{name} was not found. Install Foundry (https://foundry.paradigm.xyz) and "
        f"run `foundryup`, or set PULSAR_{name.upper()}=/path/to/{name}."
    )


def cast_path() -> str:
    return bin_path("cast")


def forge_path() -> str:
    return bin_path("forge")


def anvil_path() -> str:
    return bin_path("anvil")


def foundry_path_env() -> str:
    """PATH with the Foundry directory prepended, for `subprocess` children.

    Used by the scripts that re-launch `start_anvil.sh`: the child is a shell
    script that searches PATH itself, so it only needs to be told where to look.
    Degrades to the inherited PATH when Foundry is missing — the child then
    prints its own error, which is the message a reader should see.
    """
    inherited = os.environ.get("PATH", "")
    try:
        return str(Path(anvil_path()).parent) + os.pathsep + inherited
    except FoundryMissing:
        return inherited
