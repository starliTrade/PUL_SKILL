#!/usr/bin/env python3
"""Generate the README's test-count table from a real run (audit M-17).

The README carried 202/278/81 by hand; two of those were already wrong. A number
in documentation that nobody regenerates is a number that lies within a week.

    python scripts/test_counts.py            # run both suites, print the table
    python scripts/test_counts.py --json     # machine-readable
    python scripts/test_counts.py --skip-contract-claim

The contract suite is NOT run here: Foundry is not available in this repository's
container, and claiming a forge result that was never executed is exactly the
kind of statement this script exists to stop. It prints the CI status instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

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
        "vitest": web,
        "pytest": server,
        # Never invented: only a CI run may fill this in.
        "contract": {"status": "run `forge test` in CI; not measurable here"},
    }
    if args.json:
        print(json.dumps(table, indent=2))
    else:
        print("| Suite | Count |")
        print("|---|---|")
        print(f"| Frontend (vitest) | {web['tests']} passed, {web['files']} files |")
        print(f"| Server (pytest) | {server['passed']} passed, {server['skipped']} skipped |")
        print("| Contract (forge) | measured by CI, never by this script |")
        if web["failed"] or server["failed"]:
            print("\nFAILURES present — fix them before copying this table.")
    return 1 if (web["failed"] or server["failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
