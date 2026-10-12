#!/usr/bin/env bash
# PULSAR — single verification entrypoint (plan item 0.2).
#
# Every gate the project has, in one command, with one exit code. CI runs the
# same gates (see .github/workflows/ci.yml), so "green locally" and "green in
# CI" mean the same thing.
#
# Design notes:
#   - Gates are CAPABILITY-AWARE: a gate whose tool/config does not exist yet is
#     reported as SKIP with a reason, never as a silent pass. As phases land,
#     gates flip from SKIP to RUN without editing this file.
#   - A gate that RUNS and fails fails the whole run. A gate that is SKIPped
#     does not (otherwise the script would be useless before phase 0 finishes).
#   - `--strict` turns every SKIP into a failure. Use it in CI once all gates
#     are wired, so a missing tool can never be mistaken for a passing gate.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STRICT=0
[[ "${1:-}" == "--strict" ]] && STRICT=1

# --- toolchain discovery ------------------------------------------------------
# The sandbox keeps Foundry under the workspace HOME; CI installs it on PATH.
for candidate in "$HOME/.foundry/bin" /root/workspace/.foundry/bin; do
  [[ -x "$candidate/forge" ]] && export PATH="$candidate:$PATH"
done

PY="python3"
if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; fi

PASS=0; FAIL=0; SKIP=0
declare -a FAILED_NAMES=()

hr() { printf '─%.0s' {1..72}; echo; }

run_gate() { # run_gate <name> <command...>
  local name="$1"; shift
  hr
  echo "▶ $name"
  hr
  if "$@"; then
    echo "✅ PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "❌ FAIL  $name"
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

skip_gate() { # skip_gate <name> <reason>
  hr
  echo "▶ $1"
  echo "⏭  SKIP  $2"
  SKIP=$((SKIP + 1))
  if [[ "$STRICT" == "1" ]]; then
    echo "❌ FAIL  $1 (--strict: skips are failures)"
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$1 (skipped under --strict)")
  fi
}

# --- 1. TypeScript typecheck --------------------------------------------------
run_gate "typecheck (tsc --noEmit)" bun run lint

# --- 2. Frontend unit tests (vitest) — plan item 0.9 --------------------------
if [[ -f "$ROOT/vitest.config.ts" ]]; then
  run_gate "frontend unit tests (vitest)" bun run test:unit
else
  skip_gate "frontend unit tests (vitest)" "vitest not wired up yet (plan item 0.9)"
fi

# --- 3. Python lint + types — plan item 0.4/8.21 ------------------------------
if "$PY" -m ruff --version >/dev/null 2>&1; then
  run_gate "python lint (ruff)" "$PY" -m ruff check api scripts tests
else
  skip_gate "python lint (ruff)" "ruff not installed (plan item 0.4)"
fi

if "$PY" -m mypy --version >/dev/null 2>&1 && [[ -f "$ROOT/mypy.ini" ]]; then
  run_gate "python types (mypy)" "$PY" -m mypy api
else
  skip_gate "python types (mypy)" "mypy not configured yet (plan item 0.4)"
fi

# --- 4. Server tests (pytest) — plan item 0.3 ---------------------------------
if [[ -f "$ROOT/pytest.ini" ]] && "$PY" -m pytest --version >/dev/null 2>&1; then
  # Integration tests need the Firestore emulator. Auto-detect a running one so
  # `bun run verify` exercises the real Firestore path instead of skipping it.
  #
  # The env is passed to THIS gate only, never exported: the legacy suites below
  # assume the in-memory store, and a global FIRESTORE_EMULATOR_HOST makes
  # `store.create_store()` connect to the emulator, which changes their
  # behaviour (and made the HTTP E2E suite fail when this was exported).
  PYTEST_ENV=()
  if [[ -z "${FIRESTORE_EMULATOR_HOST:-}" ]] && curl -sf -o /dev/null "http://127.0.0.1:8081/" 2>/dev/null; then
    PYTEST_ENV=(env FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 "GCLOUD_PROJECT=${GCLOUD_PROJECT:-demo-pulsar}")
  fi
  # Plan item 0.12: coverage is a ratchet — .coveragerc's fail_under may
  # only go up, and it is passed explicitly so a missing config cannot silently
  # disable the gate.
  run_gate "server tests (pytest)" "${PYTEST_ENV[@]}" "$PY" -m pytest -q --cov=api --cov-report=term-missing
else
  skip_gate "server tests (pytest)" "pytest not wired up yet (plan item 0.3)"
fi

# --- 5. Legacy server suites (kept until fully migrated) ----------------------
if [[ -f "$ROOT/scripts/test_game_server.py" ]]; then
  run_gate "legacy protocol suite" "$PY" scripts/test_game_server.py
fi
if [[ -f "$ROOT/scripts/test_http_e2e.py" ]]; then
  run_gate "legacy HTTP E2E suite" "$PY" scripts/test_http_e2e.py
fi
for probe in probe_a5 probe_a6 probe_a8; do
  if [[ -f "$ROOT/scripts/$probe.py" ]]; then
    run_gate "legacy $probe" "$PY" "scripts/$probe.py"
  fi
done

# --- 6. Solidity contract tests (forge) — plan item 0.1 -----------------------
if command -v forge >/dev/null 2>&1; then
  if [[ -f "$ROOT/contracts/lib/forge-std/src/Test.sol" ]]; then
    run_gate "contract tests (forge test)" bash -c 'cd contracts && forge test'
  else
    skip_gate "contract tests (forge test)" "contracts/lib/forge-std missing — run: cd contracts && forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts --no-commit"
  fi
else
  skip_gate "contract tests (forge test)" "forge not installed"
fi

# --- 6b. Local EVM: anvil + deployed escrow — plan item 0.8 --------------------
# The three-way contract (oracle digest <-> onchain decoder <-> Solidity) can
# only be proven on a real EVM. Auto-start a background chain when one is not
# already up, so the gate runs instead of skipping on a dev machine.
if command -v anvil >/dev/null 2>&1 && [[ -f "$ROOT/contracts/lib/forge-std/src/Test.sol" ]]; then
  if ! curl -sf -o /dev/null -X POST -H 'Content-Type: application/json' \
       --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
       "http://127.0.0.1:${PULSAR_ANVIL_PORT:-8545}" 2>/dev/null; then
    echo "starting a background anvil for the chain gate…"
    bash "$ROOT/scripts/start_anvil.sh" --bg >/dev/null 2>&1 || true
  fi
  run_gate "chain tests (anvil + escrow)" "$PY" -m pytest -q -m chain
else
  skip_gate "chain tests (anvil + escrow)" "anvil or contract deps missing (plan item 0.8)"
fi

# --- 7. Contract compile gate (solc, no Foundry needed) -----------------------
if [[ -f "$ROOT/contracts/test/compile_check.js" ]]; then
  run_gate "contract compile gate (solc 0.8.20)" bun run test:contract
fi

# --- 8. E2E browser tests (playwright) — plan item 0.10 -----------------------
if [[ -f "$ROOT/playwright.config.ts" ]]; then
  run_gate "browser E2E (playwright)" bun run test:e2e
else
  skip_gate "browser E2E (playwright)" "playwright not wired up yet (plan item 0.10)"
fi

# --- summary ------------------------------------------------------------------
hr
echo "VERIFY SUMMARY"
hr
printf '  passed:  %d\n  failed:  %d\n  skipped: %d\n' "$PASS" "$FAIL" "$SKIP"
if [[ "$FAIL" -gt 0 ]]; then
  echo
  echo "failed gates:"
  for n in "${FAILED_NAMES[@]}"; do echo "  - $n"; done
  hr
  echo "❌ VERIFY FAILED"
  exit 1
fi
hr
echo "✅ VERIFY PASSED"
