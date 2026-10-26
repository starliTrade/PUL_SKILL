"""H-19 — no gate may depend on the sandbox it was audited in.

Four places called `/root/workspace/.foundry/bin/cast` by absolute path: the
ranked-flow E2E, the refund time-travel test, `scripts/chaos_suite.py` and
`scripts/runbook_drill.py`. That directory exists in the environment this
repository was audited in and nowhere else — so on a normal machine
(`~/.foundry/bin`) or in CI, three gates died with `FileNotFoundError`, which
from the outside looks exactly like "the feature is broken".

These tests pin two things:
  * the repository has no absolute sandbox paths left in executable code (the
    shell scripts' PATH *candidates* are allowed: they are fallbacks in a list,
    not the only option);
  * `scripts/foundry_bin.py` resolves a real binary on THIS machine and refuses
    a lying override instead of shelling out to it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from foundry_bin import FoundryMissing, anvil_path, cast_path, forge_path  # noqa: E402

SCAN_SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".js"}
SKIP_DIRS = {"node_modules", ".git", "out", "cache", "lib", "dist", "build", ".venv", "coverage"}

# `..$(dirname ..)`-style PATH lists are fine; an invoked absolute path is not.
ALLOWED = {
    # A candidate list, not a requirement: the loop also tries $HOME/.foundry/bin.
    "scripts/start_anvil.sh",
    "scripts/verify.sh",
    "scripts/start_live_preview.sh",
    "scripts/build_audit_package.sh",
    # Documented fallback for a JRE/jar the project does not ship; both have an
    # env override and a PATH-based primary path.
    "scripts/start_emulator.sh",
    # The resolver itself: its last-resort entry and its docstring must name the
    # path they are replacing. Ordering is asserted separately, below.
    "scripts/foundry_bin.py",
    # This file quotes the path in order to forbid it.
    "tests/unit/test_no_sandbox_paths.py",
}


def _files() -> list[Path]:
    out: list[Path] = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            path = Path(base) / name
            if path.suffix in SCAN_SUFFIXES:
                out.append(path)
    return out


def test_no_absolute_sandbox_paths_in_executable_code() -> None:
    offenders: list[str] = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if "/root/workspace" in text:
            offenders.append(rel)
    assert not offenders, (
        "these files hardcode the audit sandbox's paths, so they fail on any "
        f"other machine: {sorted(offenders)} — resolve through scripts/foundry_bin.py"
    )


def test_the_emulator_jar_lands_somewhere_writable() -> None:
    """H-19 again, in the one place the allowlist does not cover.

    `scripts/start_emulator.sh` may name the sandbox's JRE — it has an env
    override and a PATH-based primary. Its JAR default was different in kind:
    `/root/workspace/.tools/firestore/...` was the ONLY location, its `mkdir -p`
    fails on a CI runner, and `set -e` turned that into exit 1. `verify.sh` starts
    the emulator with `|| true`, so the run continued: the emulator gate skipped,
    the Playwright stack refused to start (it defaults to the firestore store),
    and the browser gate failed with "only 0 E2E tests ran". One unwritable path,
    three symptoms, none of which named the path.
    """
    lines = (ROOT / "scripts" / "start_emulator.sh").read_text(encoding="utf-8").splitlines()
    jar_lines = [ln for ln in lines if ln.startswith("JAR=") and "PULSAR_EMULATOR_JAR" in ln]
    cache_lines = [ln for ln in lines if ln.startswith("CACHE_DIR=")]
    assert jar_lines and cache_lines, "the JAR/CACHE_DIR lines moved; update this test with them"
    default = jar_lines[0]
    assert "/root/workspace" not in default, (
        f"the jar default is a sandbox path that does not exist elsewhere: {default}"
    )
    assert "$CACHE_DIR" in default, f"the jar default must come from CACHE_DIR: {default}"
    assert "XDG_CACHE_HOME" in cache_lines[0] and "HOME" in cache_lines[0], (
        f"the cache directory must be per-user: {cache_lines[0]}"
    )


def test_the_browser_gate_asks_for_memory_mode_when_there_is_no_emulator() -> None:
    """A missing emulator must not be reported as a failing product.

    The E2E stack defaults to the firestore store and refuses to start without
    one — correct, because a silent fallback is how durability stopped being
    tested. But `verify.sh` knows the answer already, so it states the mode
    explicitly instead of letting Playwright fail with zero tests run.
    """
    source = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    assert "PULSAR_E2E_STORE=memory" in source, (
        "verify.sh lets the E2E stack fail when no emulator is running"
    )
    assert "durability NOT exercised" in source, (
        "the memory-mode run must say what it is not testing"
    )


def test_the_legacy_path_is_only_a_last_resort() -> None:
    source = (ROOT / "scripts" / "foundry_bin.py").read_text(encoding="utf-8")
    assert "shutil.which" in source, "PATH must be tried before any fixed directory"

    import foundry_bin  # noqa: PLC0415

    # The ORDER of the fallback tuple is the contract: the official installer's
    # directory first, the audit sandbox last.
    dirs = [str(d) for d in foundry_bin._FALLBACK_DIRS]
    assert dirs[-1] == "/root/workspace/.foundry/bin"
    assert any(".foundry" in d and d.startswith(str(Path.home())) for d in dirs[:-1])


def test_it_resolves_real_binaries_on_this_machine() -> None:
    try:
        cast, forge, anvil = cast_path(), forge_path(), anvil_path()
    except FoundryMissing as exc:  # pragma: no cover - depends on the machine
        pytest.skip(str(exc))
    for binary in (cast, forge, anvil):
        assert os.access(binary, os.X_OK), binary
    out = subprocess.run(  # noqa: S603 — a resolved absolute path, no shell
        [cast, "--version"], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert "cast" in (out.stdout + out.stderr).lower()


def test_an_explicit_override_is_honoured_and_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "cast"
    fake.write_text("#!/bin/sh\necho fake-cast\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PULSAR_CAST", str(fake))
    assert cast_path() == str(fake)

    monkeypatch.setenv("PULSAR_CAST", str(tmp_path / "missing"))
    with pytest.raises(FoundryMissing, match="not executable"):
        cast_path()


def test_a_missing_binary_explains_how_to_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("PULSAR_CAST", "")
    import foundry_bin  # noqa: PLC0415

    monkeypatch.setattr(foundry_bin, "_FALLBACK_DIRS", (tmp_path / "nope",))
    with pytest.raises(FoundryMissing) as err:
        foundry_bin.cast_path()
    message = str(err.value)
    assert "foundry.paradigm.xyz" in message
    assert "PULSAR_CAST" in message


def test_the_scripts_use_the_resolver_not_a_hardcoded_path() -> None:
    for rel in (
        "scripts/chaos_suite.py",
        "scripts/runbook_drill.py",
        "tests/integration/test_refund_after_timeout.py",
        "tests/integration/test_ranked_flow_e2e.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "foundry_bin" in text, f"{rel} does not use the shared resolver"
        assert not re.search(r'["\']/[^"\']*/\.foundry/bin/cast["\']', text), (
            f"{rel} still hardcodes a cast path"
        )
