#!/usr/bin/env bash
# Assemble the external-audit package (plan item 11.3 / release gate).
#
# An auditor should not have to reconstruct the project to review it, and a
# package assembled by hand is a package that goes stale. This builds it from
# the repository every time, so what an auditor receives is exactly what the
# commit contains.
#
# History (2026-10-25). The first version of this script shipped SIX server
# files out of the 22 the server actually imports — an auditor would have
# received `main.py` with no `metrics.py`, `eventlog.py`, `timebase.py`,
# `limits.py` or `privacy.py`, i.e. code that cannot even be read, let alone
# reviewed. It also shipped no dependency lock, no server tests, and no
# integrity manifest, and it recorded the commit without recording whether the
# WORKING TREE was clean — so a package built from edited files claimed to be a
# package of the commit. All four are fixed here, and
# `tests/unit/test_audit_package.py` fails if the module set ever shrinks again.
#
# Usage:
#   scripts/build_audit_package.sh [output-dir]
#
#   AUDIT_PACKAGE_FAST=1   skip the slow evidence steps (forge coverage and the
#                          full verify.sh). The package is then marked
#                          "INCOMPLETE EVIDENCE" in PROVENANCE.md, on purpose:
#                          a fast package must never look like a full one.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/tmp/pulsar-audit-package}"
STAGE="$OUT/pulsar-audit"
FAST="${AUDIT_PACKAGE_FAST:-0}"

rm -rf "$STAGE"
mkdir -p "$STAGE"/{contracts,server,tests,docs,evidence}

echo "collecting the contract, its tests and its deploy script…"
cp "$ROOT/contracts/PulsarEscrow.sol" "$STAGE/contracts/"
# Every test file, INCLUDING the mock tokens: `MockUSDT.sol` and
# `BlacklistingUSDT.sol` define the adversarial behaviour the suite relies on,
# and a reviewer who tries to run the tests without them gets compile errors.
cp "$ROOT"/contracts/test/*.sol "$STAGE/contracts/"
cp "$ROOT/contracts/foundry.toml" "$STAGE/contracts/" 2>/dev/null || true
mkdir -p "$STAGE/contracts/script"
cp "$ROOT"/contracts/script/*.sol "$STAGE/contracts/script/" 2>/dev/null || true

echo "collecting the WHOLE server, not just the files named in the README…"
cp "$ROOT"/api/*.py "$STAGE/server/"
cp "$ROOT"/api/requirements*.txt "$STAGE/server/" 2>/dev/null || true
cp "$ROOT"/mypy.ini "$ROOT"/.coveragerc "$ROOT"/.coveragerc-hermetic "$STAGE/server/" 2>/dev/null || true
cp "$ROOT"/requirements*.txt "$STAGE/server/" 2>/dev/null || true

echo "collecting the server test suite…"
mkdir -p "$STAGE/tests"
cp -r "$ROOT"/tests/. "$STAGE/tests/" 2>/dev/null || true
# `__pycache__` and the coverage data file are build artefacts, not source.
find "$STAGE/tests" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/tests" -name '*.pyc' -delete 2>/dev/null || true
cp "$ROOT"/pytest.ini "$STAGE/" 2>/dev/null || true
cp "$ROOT"/conftest.py "$STAGE/" 2>/dev/null || true

echo "collecting the documents an auditor needs…"
cp "$ROOT/docs/audit/PACKAGE-README.md" "$STAGE/"
for f in \
  audit/FULL-AUDIT-2026-10-12.md \
  audit/RUTHLESS-AUDIT-2026-10-22.md \
  audit/REMEDIATION-TODO-2026-10-22.md \
  HOW-IT-WORKS.md \
  DEPLOYMENT.md \
  INCIDENT-RUNBOOK.md \
  UPGRADE-PATH.md \
  COVERAGE-REPORT.md \
  USER-TODO.md \
  FINAL-REPORT.md \
  plans/MASTER-PLAN.md
do
  [[ -f "$ROOT/docs/$f" ]] && cp "$ROOT/docs/$f" "$STAGE/docs/"
done
cp "$ROOT"/scripts/verify.sh "$STAGE/evidence/" 2>/dev/null || true

echo "recording the commit this package was built from…"
{
  echo "# Provenance"
  echo
  echo "Commit: \`$(git -C "$ROOT" rev-parse HEAD)\`"
  echo "Branch: \`$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)\`"
  echo "Built:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  # The tree state is recorded BEFORE the file list, because it changes how
  # everything below it must be read: a dirty tree means the files in this
  # package are NOT the files in that commit.
  dirty="$(git -C "$ROOT" status --porcelain 2>/dev/null || true)"
  if [[ -n "$dirty" ]]; then
    echo "## Working tree: DIRTY — this package does NOT match the commit above"
    echo
    echo '```'
    echo "$dirty"
    echo '```'
  else
    echo "## Working tree: clean — the files below are the files in that commit"
  fi
  echo
  echo "## Evidence"
  echo
  if [[ "$FAST" == "1" ]]; then
    echo "**INCOMPLETE: built with AUDIT_PACKAGE_FAST=1.** No forge coverage and"
    echo "no verify.sh run is included. Rebuild without the flag before sending"
    echo "this to an auditor."
  else
    echo "forge coverage and verify.sh output are in this directory."
  fi
  echo
  echo "## Contract coverage"
  echo
  export PATH="$PATH:/root/workspace/.foundry/bin"
  if [[ "$FAST" == "1" ]]; then
    echo "(skipped: AUDIT_PACKAGE_FAST=1)"
  elif command -v forge >/dev/null 2>&1; then
    # `forge coverage` prints the TEST RUN first, and those lines contain
    # "PulsarEscrow" — so a naive grep captured the test list instead of the
    # coverage table, which is the opposite of evidence. The table rows are the
    # ones with pipes.
    (cd "$ROOT/contracts" && forge coverage --report summary 2>/dev/null \
      | grep -E "^\|" | grep -E "PulsarEscrow|Total" || echo "(coverage run failed)")
  else
    echo "(forge not available where this package was built — run \`forge coverage\` yourself)"
  fi
  echo
  echo "## Contract test inventory"
  echo
  for f in "$ROOT"/contracts/test/*.t.sol; do
    tests=$(grep -c 'function test' "$f" || true)
    invariants=$(grep -c 'function invariant_' "$f" || true)
    printf -- "- %s: %s test functions, %s invariants\n" "$(basename "$f")" "$tests" "$invariants"
  done
} > "$STAGE/evidence/PROVENANCE.md"

if [[ "$FAST" != "1" ]]; then
  echo "recording the verify gate output…"
  if [[ -x "$ROOT/scripts/verify.sh" ]]; then
    # A failing gate is itself evidence, so this does not abort on failure.
    (cd "$ROOT" && timeout 1800 bash scripts/verify.sh 2>&1 | tail -60) > "$STAGE/evidence/VERIFY-OUTPUT.txt" || true
  fi
fi

echo "writing the integrity manifest…"
# Every file in the package, so an auditor can prove nothing was added or
# changed in transit. Written AFTER the evidence, so the manifest covers it.
( cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum ) \
  > "$STAGE/SHA256SUMS"

echo "packing…"
( cd "$OUT" && tar czf pulsar-audit-package.tar.gz pulsar-audit )

echo
echo "================================================================"
echo "  $OUT/pulsar-audit-package.tar.gz"
echo "================================================================"
echo
echo "Contents:"
( cd "$STAGE" && find . -type f | sort | sed 's/^/  /' )
