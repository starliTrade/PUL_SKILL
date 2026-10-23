#!/usr/bin/env python3
"""Generate the README's test-count table from a real run (audit M-17).

The README carried 202/278/81 by hand; two of those were already wrong. A number
in documentation that nobody regenerates is a number that lies within a week.

    python scripts/test_counts.py            # run both suites, print the table
    python scripts/test_counts.py --json     # machine-readable
    python scripts/test_counts.py --skip-contract-claim

The contract suite is measured when Foundry is actually installed (`forge` on
PATH and `contracts/lib/forge-std` present); when it is not, the script says so
instead of printing a number. Claiming a forge result that was never executed is
exactly the kind of statement this script exists to stop — but refusing to look
once Foundry IS available is the same dishonesty in the other direction.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed commands, no shell
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    return (proc.stdout or "") + (proc.stderr or "")


def pytest_counts() -> dict[str, int]:
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    python = venv if os.path.exists(venv) else sys.executable
    out = _run(
        [python, "-m", "pytest", "-q"],
        {"PULSAR_ENV": "dev", "ORACLE_SIGNING_SECRET": "counts-only-not-a-secret"},
    )
    passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1])
    skipped = int((re.search(r"(\d+) skipped", out) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", out) or [0, 0])[1])
    return {"passed": passed, "skipped": skipped, "failed": failed}


def vitest_counts() -> dict[str, int]:
    out = _run(["npx", "vitest", "run", "--reporter=dot"])
    clean = re.sub(r"\x1b\[[0-9;]*m", "", out)
    tests = int((re.search(r"Tests\s+(\d+) passed", clean) or [0, 0])[1])
    files = int((re.search(r"Test Files\s+(\d+) passed", clean) or [0, 0])[1])
    failed = int((re.search(r"Tests\s+.*?(\d+) failed", clean) or [0, 0])[1])
    return {"tests": tests, "files": files, "failed": failed}


def forge_counts() -> dict[str, object]:
    """Measure the contract suite — only if Foundry is really installed."""
    forge = shutil.which("forge")
    if forge is None:
        return {"status": "forge not installed - not measurable here"}
    if not os.path.exists(os.path.join(ROOT, "contracts", "lib", "forge-std", "src", "Test.sol")):
        return {
            "status": (
                "deps missing - run: cd contracts && "
                "forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts --no-commit"
            )
        }
    out = _run([forge, "test", "--root", os.path.join(ROOT, "contracts")])
    clean = re.sub(r"\x1b\[[0-9;]*m", "", out)
    match = re.search(r"Ran (\d+) test suites.*?: (\d+) tests passed, (\d+) failed", clean)
    if not match:
        return {"status": "forge test produced no summary - see the output above"}
    return {
        "suites": int(match.group(1)),
        "passed": int(match.group(2)),
        "failed": int(match.group(3)),
        "measured": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the suites for the README")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--skip-vitest", action="store_true", help="print only the pytest numbers (fast)"
    )
    args = parser.parse_args(argv)

    server = pytest_counts()
    web = {"tests": 0, "files": 0, "failed": 0} if args.skip_vitest else vitest_counts()

    table = {
        "vitest": web if not args.skip_vitest else {"skipped": True},
        "pytest": server,
        # Never invented: either measured by a real `forge test`, or it says why not.
        "contract": forge_counts(),
    }
    if args.json:
        print(json.dumps(table, indent=2))
    else:
        print("| Suite | Count |")
        print("|---|---|")
        if args.skip_vitest:
            print("| Frontend (vitest) | not measured (--skip-vitest) |")
        else:
            print(f"| Frontend (vitest) | {web['tests']} passed, {web['files']} files |")
        print(f"| Server (pytest) | {server['passed']} passed, {server['skipped']} skipped |")
        contract = table["contract"]
        if "passed" in contract:
            print(
                f"| Contract (forge) | {contract['passed']} tests, "
                f"{contract['suites']} suites, measured {contract['measured']} |"
            )
        else:
            print(f"| Contract (forge) | {contract['status']} |")
        failed = (
            (bool(web["failed"]) and not args.skip_vitest)
            or bool(server["failed"])
            or bool(contract.get("failed", 0))
        )
        if failed:
            print("\nFAILURES present — fix them before copying this table.")
    failed = (
        (bool(web["failed"]) and not args.skip_vitest)
        or bool(server["failed"])
        or bool(table["contract"].get("failed", 0))
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
