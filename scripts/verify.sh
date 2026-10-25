#!/usr/bin/env bash
# PULSAR — single verification entrypoint (plan item 0.2).
#
# Every gate the project has, in one command, with one exit code.
#
# CORRECTED 2026-10-16: this used to say "CI runs the same gates (see
# .github/workflows/ci.yml), so 'green locally' and 'green in CI' mean the same
# thing" — and that was FALSE. An adversarial audit found that chaos, the runbook
# drill, alerting, the refund time-travel suite, the live-stack ranked flow and
# both probes run NOWHERE in CI. So "green in CI" was a weaker claim than this
# comment implied, and every fix that landed on those gates was unprotected.
#
# I tried to close the gap (a `verify-gates` CI job running this script) and
# could not make it work: the job fails at `scripts/start_anvil.sh --bg` on a
# clean runner. Rather than merge a red CI or leave a broken job, the claim is
# removed. The truth is:
#
#   CI runs: typecheck, frontend unit, ruff, mypy, pytest, the coverage ratchet,
#            forge test, chain tests, contract coverage, the solc gate.
#   CI does NOT run: the browser E2E, the live-stack ranked flow, the eligibility
#            gate, the refund time-travel suite, alerting, the runbook drill,
#            the chaos suite, or the legacy probes.
#
# Closing that gap is worth doing and is not done. Do not re-add a parity claim
# until a CI job actually runs this script.
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

# Audit L-04: this script used `bun run` for four gates. On a machine without
# bun, `verify` died at the typecheck with `bun: not found` — the whole gate
# looked red for a missing launcher, not for a defect. npm is a supported path
# (the scripts in package.json are portable), so use whichever is installed.
if command -v bun >/dev/null 2>&1; then
  RUN="bun run"
elif command -v npm >/dev/null 2>&1; then
  RUN="npm run"
else
  echo "neither bun nor npm is installed — cannot run the JS gates" >&2
  exit 2
fi
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

run_gate_skippable() { # run_gate_skippable <name> <command...>
  # A gate whose suite can legitimately report "I exercised some scenarios and
  # skipped others because the environment is missing a service".
  #
  # Audit 2026-10-24: the chaos suite folded those into its failure list, so a
  # machine without a JRE produced four red lines that meant "Java is not
  # installed" — and the summary read as if the server were broken. The suite now
  # separates them; this wrapper turns its machine-readable line into a SKIP with
  # a reason. It is deliberately NOT a pass: a skipped scenario is still
  # unverified, and `--strict` still fails the run.
  local name="$1"; shift
  local log
  log="$(mktemp)"
  hr
  echo "▶ $name"
  hr
  if "$@" >"$log" 2>&1; then
    cat "$log"
    if grep -q '^SKIPPED (environment)' "$log"; then
      echo "⏭  SKIP  $name — scenarios NOT exercised (environment):"
      sed -n '/^SKIPPED (environment)/,$p' "$log" | sed 's/^/     /'
      SKIP=$((SKIP + 1))
      if [[ "$STRICT" == "1" ]]; then
        echo "❌ FAIL  $name (--strict: a skipped scenario is a failure)"
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name (skipped under --strict)")
      fi
    else
      echo "✅ PASS  $name"
      PASS=$((PASS + 1))
    fi
  else
    cat "$log"
    echo "❌ FAIL  $name"
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
  rm -f "$log"
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
run_gate "typecheck (tsc --noEmit)" $RUN lint

# --- 2. Frontend unit tests (vitest) — plan item 0.9 --------------------------
if [[ -f "$ROOT/vitest.config.ts" ]]; then
  run_gate "frontend unit tests (vitest)" $RUN test:unit
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
  # --- 4a. HERMETIC coverage gate (audit M-15, 2026-10-22) -------------------
  #
  # This runs FIRST and always: no emulator, no anvil, no network. The floor in
  # `.coveragerc-hermetic` was measured on this configuration, so the number
  # cannot move just because a service happens to be running (the old single
  # gate reported 74% without the emulator and 79% with it — same code).
  #
  # FIRESTORE_EMULATOR_HOST is unset explicitly: some modules decide to skip
  # their tests by reading it at import time, so an inherited value would change
  # what runs and therefore what is measured.
  if "$PY" -m coverage --version >/dev/null 2>&1; then
    HERMETIC_ARGS=(-q -m "not emulator and not chain")
    if [[ -n "${FIRESTORE_EMULATOR_HOST:-}" ]]; then
      env -u FIRESTORE_EMULATOR_HOST "$PY" -m coverage erase --rcfile=.coveragerc-hermetic
      run_gate "server tests (pytest, hermetic coverage)" \
        env -u FIRESTORE_EMULATOR_HOST "$PY" -m coverage run --rcfile=.coveragerc-hermetic \
        --source=api -m pytest "${HERMETIC_ARGS[@]}"
    else
      "$PY" -m coverage erase --rcfile=.coveragerc-hermetic
      run_gate "server tests (pytest, hermetic coverage)" \
        "$PY" -m coverage run --rcfile=.coveragerc-hermetic --source=api -m pytest "${HERMETIC_ARGS[@]}"
    fi
    run_gate "coverage ratchet, hermetic (fail_under in .coveragerc-hermetic)" \
      "$PY" -m coverage report --rcfile=.coveragerc-hermetic --skip-covered
    COVERAGE_ACTIVE=0   # the full session below starts a fresh data file
  else
    run_gate "server tests (pytest)" "$PY" -m pytest -q
    COVERAGE_ACTIVE=0
  fi

  # --- 4b. COMPLETE coverage gate (emulator + anvil) -------------------------
  #
  # The higher number, and a separate gate whose NAME says what it needs. It is
  # skipped — loudly — when the services are absent, because it cannot be
  # measured there; the hermetic gate above is what must always be green.
  if ! curl -sf -o /dev/null "http://127.0.0.1:8081/" 2>/dev/null; then
    echo "starting a background Firestore emulator for the complete coverage gate…"
    bash "$ROOT/scripts/start_emulator.sh" --bg >/dev/null 2>&1 || true
  fi

  if curl -sf -o /dev/null "http://127.0.0.1:8081/" 2>/dev/null; then
    PYTEST_ENV=(env FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 "GCLOUD_PROJECT=${GCLOUD_PROJECT:-demo-pulsar}")
    if "$PY" -m coverage --version >/dev/null 2>&1; then
      "$PY" -m coverage erase
      run_gate "server tests + emulator (complete coverage)" \
        "${PYTEST_ENV[@]}" "$PY" -m coverage run --source=api -m pytest -q
      COVERAGE_ACTIVE=1
    fi
  else
    skip_gate "complete coverage gate (emulator + anvil)" \
      "no Firestore emulator on 127.0.0.1:8081 — the hermetic gate above is the one that must hold"
    COVERAGE_ACTIVE=0
  fi
else
  skip_gate "server tests (pytest)" "pytest not wired up yet (plan item 0.3)"
  COVERAGE_ACTIVE=0
fi

# --- 5. Legacy server suites (kept until fully migrated) ----------------------
# Run under the SAME coverage session as pytest so the ratchet sees the truth.
legacy_run() { # legacy_run <name> <script>
  local name="$1" script="$2"
  if [[ "${COVERAGE_ACTIVE:-0}" == "1" ]]; then
    run_gate "$name" "$PY" -m coverage run --append --source=api "$script"
  else
    run_gate "$name" "$PY" "$script"
  fi
}

if [[ -f "$ROOT/scripts/test_game_server.py" ]]; then
  legacy_run "legacy protocol suite" scripts/test_game_server.py
fi
if [[ -f "$ROOT/scripts/test_http_e2e.py" ]]; then
  legacy_run "legacy HTTP E2E suite" scripts/test_http_e2e.py
fi
for probe in probe_a5 probe_a6 probe_a8; do
  if [[ -f "$ROOT/scripts/$probe.py" ]]; then
    legacy_run "legacy $probe" "scripts/$probe.py"
  fi
done

# --- 5b. Coverage ratchet over the whole server suite — plan item 0.12 --------
if [[ "${COVERAGE_ACTIVE:-0}" == "1" ]]; then
  run_gate "coverage ratchet (.coveragerc fail_under)" bash -c \
    '"$0" -m coverage report --skip-covered' "$PY"
fi

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

# --- 6c. Contract coverage — plan item CT13 -----------------------------------
# `forge coverage` has no fail-under, so the floor is enforced here. Only the
# escrow is gated: the test helpers are scaffolding, and Deploy.s.sol is a
# script that no test executes.
if command -v forge >/dev/null 2>&1 && [[ -f "$ROOT/contracts/lib/forge-std/src/Test.sol" ]]; then
  run_gate "contract coverage (PulsarEscrow.sol >= 95% lines)" bash -c '
    set -euo pipefail
    cd contracts
    out="$(forge coverage --report summary 2>/dev/null)"
    line="$(printf "%s" "$out" | grep -E "^\| PulsarEscrow\.sol" | head -1)"
    pct="$(printf "%s" "$line" | awk -F"|" "{print \$3}" | grep -oE "[0-9]+\.[0-9]+" | head -1)"
    echo "PulsarEscrow.sol line coverage: ${pct}%"
    awk -v p="$pct" "BEGIN { exit !(p+0 >= 95) }"
  '
else
  skip_gate "contract coverage (PulsarEscrow.sol >= 95% lines)" "forge or contract deps missing"
fi

# --- 7. Contract compile gate (solc, no Foundry needed) -----------------------
if [[ -f "$ROOT/contracts/test/compile_check.js" ]]; then
  run_gate "contract compile gate (solc 0.8.20)" $RUN test:contract
fi

# --- 8. E2E browser tests (playwright) — plan item 0.10 -----------------------
if [[ -f "$ROOT/playwright.config.ts" ]]; then
  # The E2E drives the REAL stack: the API starts with the escrow address, RPC
  # and oracle key set, so anvil must be up with the escrow deployed. Start it
  # the same way the emulator is started above, rather than failing on a
  # prerequisite the gate can satisfy itself.
  if ! curl -sf -o /dev/null -X POST -H "Content-Type: application/json" \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
      "http://127.0.0.1:${PULSAR_ANVIL_PORT:-8545}" 2>/dev/null; then
    if [[ -x "$ROOT/scripts/start_anvil.sh" ]]; then
      PATH="$PATH:/root/workspace/.foundry/bin" bash "$ROOT/scripts/start_anvil.sh" --bg >/dev/null 2>&1 || true
    fi
  fi
  if curl -sf -o /dev/null -X POST -H "Content-Type: application/json" \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
      "http://127.0.0.1:${PULSAR_ANVIL_PORT:-8545}" 2>/dev/null; then
    # A FRESH stack. The E2E specs pair anvil's deterministic players, and the
    # live-stack gate above has already used them — so without this the money-path
    # specs skip or fail on a stale match, which reads as a product failure.
    bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
    sleep 2
    bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1 || true
    # Audit 2026-10-16: Playwright exits 0 when every test SKIPS, and three
# money-path specs skip when the shared store holds a stale match. So this gate
# could pass while executing nothing — the same false-green class the server
# pytest job already guards against with a minimum-count check. Capture the
# output and require that tests actually ran.
run_gate "browser E2E (playwright, min 20 tests)" bash -c \
  "cd '$ROOT' && $RUN test:e2e 2>&1 | tee /tmp/pulsar-e2e.log; \
   passed=\$(grep -oE '[0-9]+ passed' /tmp/pulsar-e2e.log | tail -1 | grep -oE '[0-9]+' || echo 0); \
   if [ \"\$passed\" -lt 20 ]; then \
     echo \"only \$passed E2E tests ran (expected >= 20) — skips are not coverage\"; \
     exit 1; \
   fi"
  else
    skip_gate "browser E2E (playwright)" "anvil is not running — run scripts/start_anvil.sh --bg"
  fi
else
  skip_gate "browser E2E (playwright)" "playwright not wired up yet (plan item 0.10)"
fi

# --- 8b. Live-stack integration — the tests that need a running API -----------
#
# Audit 2026-10-14: `tests/integration/test_ranked_flow_e2e.py` and its reads
# assertion SKIP without a live API on :8000, and the pytest gate above runs
# before any API exists — so the ranked money path was verified by tests that
# never executed in a gate. This gate starts the stack and runs them for real.
if [[ -x "$ROOT/scripts/start_e2e_stack.sh" ]]; then
  # --stop FIRST: starting without it leaves a stale server holding the port,
  # whose in-process cache makes these tests skip against a wiped store.
  bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
  sleep 2
  if bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1; then
    # PULSAR_FAIL_ON_SKIP: this gate exists to prove these tests RUN. A skip is
    # not coverage, and pytest's exit code does not care about skips — so
    # without this the gate passed while executing nothing.
    # Audit 2026-10-16: this gate ran ONLY the ranked flow. The eligibility gate's
    # five tests skip without a live API, so they skipped in every other gate too
    # — meaning `eligibility.require` in api/main.py was guarded by ZERO
    # executing tests, and deleting that one line would have kept CI green.
    run_gate "live-stack integration (ranked flow + reads + eligibility)" bash -c \
      "cd '$ROOT' && PULSAR_FAIL_ON_SKIP=1 \
       FIRESTORE_EMULATOR_HOST=127.0.0.1:${PULSAR_FIRESTORE_PORT:-8081} \
       GCLOUD_PROJECT=demo-pulsar '$PY' -m pytest \
         tests/integration/test_ranked_flow_e2e.py \
         tests/integration/test_eligibility_gate.py -q -p no:cacheprovider"
  else
    skip_gate "live-stack integration (ranked flow + reads)" "the E2E stack did not start"
  fi
else
  skip_gate "live-stack integration (ranked flow + reads)" "scripts/start_e2e_stack.sh is missing"
fi

# --- 8c. Refund after timeout (time travel) — plan item 10.1 ------------------
#
# Audit 2026-10-14: this test skips unless PULSAR_TEST_TIME_TRAVEL=1, and NOTHING
# set that flag — so the refund path was claimed verified by a test that never
# ran. It moves the chain clock forward and anvil cannot rewind it, so it runs
# here, on its own, and the chain is restarted afterwards.
if [[ -f "$ROOT/tests/integration/test_refund_after_timeout.py" ]]; then
  run_gate "refund after timeout (time travel)" bash -c \
    "cd '$ROOT' && PULSAR_TEST_TIME_TRAVEL=1 PULSAR_FAIL_ON_SKIP=1 \
     FIRESTORE_EMULATOR_HOST=127.0.0.1:${PULSAR_FIRESTORE_PORT:-8081} GCLOUD_PROJECT=demo-pulsar \
     '$PY' -m pytest tests/integration/test_refund_after_timeout.py -q -p no:cacheprovider"
  # The chain is now hours ahead of the server; the oracle signs a deadline from
  # the server's clock and the contract enforces the chain's, so anything that
  # settles would fail. Put the chain back.
  pkill -f "anvil --port ${PULSAR_ANVIL_PORT:-8545}" 2>/dev/null || true
  sleep 2
  PATH="$PATH:/root/workspace/.foundry/bin" bash "$ROOT/scripts/start_anvil.sh" --bg >/dev/null 2>&1 || true
  # The API must be restarted TOO, and this is not tidiness.
  #
  # Audit 2026-10-16: restarting anvil REDEPLOYS, so the escrow address changes.
  # The API was left holding the old one, so every gate after this point — the
  # runbook drill and the whole chaos suite — failed with "On-chain duel state
  # cannot be verified", which reads like a server bug and was a stale address.
  # Both gates PASSED when run alone and FAILED only in the full run, which is
  # exactly the signature of an ordering dependency nobody had written down.
  bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
  sleep 1
  bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1 || true
fi

# --- 8c2. Alerting — plan item 11.2 ------------------------------------------
#
# The metrics existed and nothing watched them. This gate proves the alerting
# path works AND that it stays quiet when the server is healthy — an alert that
# fires on a healthy server is worse than none, because it trains people to
# ignore it.
if [[ -f "$ROOT/scripts/check_alerts.py" ]]; then
  run_gate "alerting (healthy server must be quiet)" bash -c \
    "cd '$ROOT' && '$PY' scripts/check_alerts.py --quiet"
else
  skip_gate "alerting (healthy server must be quiet)" "scripts/check_alerts.py is missing"
fi

# --- 8c3. Runbook drill — plan item 11.2 -------------------------------------
#
# "Runbook rehearsed" means an operator who has never seen this system can follow
# the document and reach the right conclusion. So this tests the DOCUMENT: it
# breaks the RPC and asserts every signal the runbook names reads what the
# runbook says it will.
if [[ -f "$ROOT/scripts/runbook_drill.py" ]]; then
  run_gate "runbook drill (the document matches the server)" bash -c \
    "cd '$ROOT' && '$PY' scripts/runbook_drill.py"
else
  skip_gate "runbook drill (the document matches the server)" "scripts/runbook_drill.py is missing"
fi

# --- 8d. Chaos suite — plan item 10.4 ----------------------------------------
#
# Audit 2026-10-14: `scripts/chaos_suite.py` was referenced by NOTHING — not this
# script, not CI, not package.json. Nineteen checks that no gate ever ran.
if [[ -f "$ROOT/scripts/chaos_suite.py" ]]; then
  # The suite pairs the manifest's players, and earlier gates have already used
  # them — so it needs a FRESH stack, or its control fails on a stale match
  # rather than on the thing it is testing.
  bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
  sleep 2
  bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1 || true
  run_gate_skippable "chaos suite (rpc/firestore/replica/delay/soak)" bash -c \
    "cd '$ROOT' && FIRESTORE_EMULATOR_HOST=127.0.0.1:${PULSAR_FIRESTORE_PORT:-8081} \
     GCLOUD_PROJECT=demo-pulsar '$PY' scripts/chaos_suite.py"
else
  skip_gate "chaos suite (rpc/firestore/replica/delay/soak)" "scripts/chaos_suite.py is missing"
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
