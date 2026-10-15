#!/usr/bin/env bash
# Assemble the external-audit package (plan item 11.3 / release gate).
#
# An auditor should not have to reconstruct the project to review it, and a
# package assembled by hand is a package that goes stale. This builds it from
# the repository every time, so what an auditor receives is exactly what the
# commit contains.
#
# Usage: scripts/build_audit_package.sh [output-dir]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/tmp/pulsar-audit-package}"
STAGE="$OUT/pulsar-audit"

rm -rf "$STAGE"
mkdir -p "$STAGE"/{contracts,tests,docs,evidence}

echo "collecting the contract and its tests…"
cp "$ROOT/contracts/PulsarEscrow.sol" "$STAGE/contracts/"
cp "$ROOT"/contracts/test/*.t.sol "$STAGE/contracts/"
cp "$ROOT/contracts/foundry.toml" "$STAGE/contracts/" 2>/dev/null || true

echo "collecting the server-side money path…"
mkdir -p "$STAGE/server"
for f in oracle.py onchain.py store.py match_engine.py main.py auth.py; do
  [[ -f "$ROOT/api/$f" ]] && cp "$ROOT/api/$f" "$STAGE/server/"
done

echo "collecting the documents an auditor needs…"
cp "$ROOT/docs/audit/PACKAGE-README.md" "$STAGE/"
cp "$ROOT/docs/audit/FULL-AUDIT-2026-10-12.md" "$STAGE/docs/" 2>/dev/null || true
cp "$ROOT/docs/HOW-IT-WORKS.md" "$STAGE/docs/" 2>/dev/null || true
cp "$ROOT/docs/DEPLOYMENT.md" "$STAGE/docs/" 2>/dev/null || true
cp "$ROOT/docs/INCIDENT-RUNBOOK.md" "$STAGE/docs/" 2>/dev/null || true
cp "$ROOT/docs/plans/MASTER-PLAN.md" "$STAGE/docs/" 2>/dev/null || true

echo "recording the commit this package was built from…"
{
  echo "# Provenance"
  echo
  echo "Commit: \`$(git -C "$ROOT" rev-parse HEAD)\`"
  echo "Branch: \`$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)\`"
  echo "Built:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## Contract coverage"
  echo
  export PATH="$PATH:/root/workspace/.foundry/bin"
  if command -v forge >/dev/null 2>&1; then
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

echo "recording the verify gate output…"
if [[ -x "$ROOT/scripts/verify.sh" ]]; then
  # A failing gate is itself evidence, so this does not abort on failure.
  (cd "$ROOT" && timeout 1800 bash scripts/verify.sh 2>&1 | tail -40) > "$STAGE/evidence/VERIFY-OUTPUT.txt" || true
fi

echo "packing…"
( cd "$OUT" && tar czf pulsar-audit-package.tar.gz pulsar-audit )

echo
echo "================================================================"
echo "  $OUT/pulsar-audit-package.tar.gz"
echo "================================================================"
echo
echo "Contents:"
( cd "$STAGE" && find . -type f | sort | sed 's/^/  /' )
