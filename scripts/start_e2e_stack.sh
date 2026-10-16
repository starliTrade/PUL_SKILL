#!/usr/bin/env bash
# PULSAR — the local stack the E2E suite drives (plan item 10.1).
#
# Starts the API against anvil + the Firestore emulator with the REAL production
# configuration (escrow address, RPC, oracle key, chain id, allowed domain), so
# the E2E exercises the same fail-closed gates a deployment does — not a dev
# bypass. Anvil and the emulator must already be running:
#
#   scripts/start_emulator.sh --bg
#   scripts/start_anvil.sh --bg      # deploys the escrow, writes the manifest
#
# Usage: scripts/start_e2e_stack.sh [--stop]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/contracts/deployments/local.json"
PIDFILE="/tmp/pulsar-e2e-api.pid"
API_PORT="${PULSAR_API_PORT:-8000}"
LOGFILE="/tmp/pulsar-e2e-api.log"
PORT="${PULSAR_E2E_API_PORT:-8000}"
FRONTEND_PORT="${PULSAR_E2E_FRONTEND_PORT:-3000}"

if [[ "${1:-}" == "--stop" ]]; then
  # Kill by PORT, not only by the recorded pid.
  #
  # Audit 2026-10-14: `--stop` killed the pid in $PIDFILE, and the startup path
  # wrote `$!` after `nohup … &`. When that pid was stale or the shell had
  # re-parented the process, an OLD API kept the port — and the next start's
  # health poll saw the old server's 200 and printed "E2E API up". The durable
  # store's in-process `player_match` cache then survived, so `/api/queue`
  # returned matches the wiped store no longer had, and tests skipped or failed
  # for reasons that looked like product bugs. This cost real debugging time
  # three separate times.
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${API_PORT:-8000}/tcp" 2>/dev/null || true
  fi
  pkill -f "uvicorn.*${API_PORT:-8000}" 2>/dev/null || true
  if [[ -f "$PIDFILE" ]]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "stopped the E2E API"
  fi
  exit 0
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "no deployment manifest at $MANIFEST — run scripts/start_anvil.sh --bg" >&2
  exit 1
fi

read_manifest() { python3 -c "import json,sys; print(json.load(open('$MANIFEST'))$1)"; }

ESCROW="$(read_manifest "['escrow']")"
RPC="$(read_manifest "['rpcUrl']")"
CHAIN_ID="$(read_manifest "['chainId']")"
ORACLE_KEY="$(read_manifest "['oracleKey']")"

# A deterministic signing secret for the test run — never a real one.
SIGNING_SECRET="0x$(printf '11%.0s' {1..32})"

# Wipe the emulator BEFORE the API starts.
#
# The durable store keeps an in-process `player_match` cache, so a wipe that
# happens after the server is up leaves it holding match ids whose documents no
# longer exist — and `/api/queue` then hands those out, which is exactly the
# `409 {"detail":"Match not found"}` this suite kept hitting. Resetting the
# store and starting the server must be one ordered step, not two.
EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8081}"
PROJECT="${FIRESTORE_PROJECT_ID:-${GCLOUD_PROJECT:-demo-pulsar}}"
if curl -sf -o /dev/null "http://${EMULATOR_HOST}/" 2>/dev/null; then
  curl -sf -o /dev/null -X DELETE \
    "http://${EMULATOR_HOST}/emulator/v1/projects/${PROJECT}/databases/(default)/documents" \
    && echo "reset the Firestore emulator (${PROJECT})"
fi

cd "$ROOT/api"
# NOTE: Starlette strips the port before matching a Host header, so
# ALLOWED_HOSTS holds HOSTNAMES (no ports).
#
# NOTE: `GCLOUD_PROJECT` only — `api/store.py` reads `FIRESTORE_PROJECT_ID` for
# its client, and setting that here made the client construction fail, which the
# store swallows into a MEMORY fallback.
#
# DO NOT PUT A COMMENT INSIDE THE ENV PREFIX BELOW. A `#` line breaks the
# backslash continuation, so the assignment list ends there and every variable
# after it becomes a separate command — the server then starts with
# `PULSAR_MATCH_STORE` unset and silently serves from memory. This has now
# happened twice in this file; that is why the warning is here.
PULSAR_MATCH_STORE=firestore \
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8081}" \
GCLOUD_PROJECT="${GCLOUD_PROJECT:-demo-pulsar}" \
CORS_ALLOW_ORIGINS="${CORS_ALLOW_ORIGINS:-http://127.0.0.1:${FRONTEND_PORT},http://localhost:${FRONTEND_PORT}}" \
ALLOWED_DOMAIN="127.0.0.1:${FRONTEND_PORT}" \
ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost}" \
ESCROW_ADDRESS="$ESCROW" \
ESCROW_RPC_URL="$RPC" \
ORACLE_PRIVATE_KEY="$ORACLE_KEY" \
ORACLE_CHAIN_ID="$CHAIN_ID" \
ORACLE_SIGNING_SECRET="$SIGNING_SECRET" \
nohup "$ROOT/.venv/bin/python" -m uvicorn main:app --port "$PORT" --log-level info \
  > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
# Verify the port is OURS, not a survivor's: a stale server answering the health
# check is indistinguishable from a fresh one, and it is what made several tests
# skip silently.
sleep 1
if command -v ss >/dev/null 2>&1; then
  OWNER_PID="$(ss -lptn "sport = :${API_PORT:-8000}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
  if [[ -n "$OWNER_PID" && "$OWNER_PID" != "$(cat "$PIDFILE")" ]]; then
    echo "port ${API_PORT:-8000} is held by pid $OWNER_PID, not the server we started ($(cat "$PIDFILE"))" >&2
    exit 1
  fi
fi

for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/health"; then
    echo "E2E API up on 127.0.0.1:${PORT} (escrow ${ESCROW:0:10}…, chain ${CHAIN_ID})"
    exit 0
  fi
  sleep 0.5
done

echo "the E2E API did not become healthy — see $LOGFILE" >&2
tail -20 "$LOGFILE" >&2 || true
exit 1# --- 0. the manifest and the CHAIN must agree ---------------------------------
#
# Audit 2026-10-16: `start_anvil.sh` REDEPLOYS on every run, so the escrow address
# changes each time. An API started before that points at an address with no code
# on it — and it reports `escrowConfigured: true` and `rpc.reachable: true` while
# every duel fails with "On-chain duel state cannot be verified right now". That
# reads like a server bug and is a stale manifest.
#
# This cost a confusing chaos-suite failure and nearly a false "fail-open deposit
# gate" finding. Check it here, loudly, before the API is started.
_manifest="${ROOT}/contracts/deployments/local.json"
if [[ -f "$_manifest" ]]; then
  _escrow="$(python3 -c "import json;print(json.load(open('$_manifest'))['escrow'])" 2>/dev/null || true)"
  if [[ -n "$_escrow" ]]; then
    _code="$(curl -s -X POST -H 'Content-Type: application/json' \
      --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$_escrow\",\"latest\"]}" \
      "${PULSAR_ANVIL_URL:-http://127.0.0.1:8545}" 2>/dev/null \
      | python3 -c "import json,sys;print(json.load(sys.stdin).get('result','0x'))" 2>/dev/null || echo 0x)"
    if [[ "$_code" == "0x" || -z "$_code" ]]; then
      echo "REFUSING TO START: the manifest names escrow $_escrow but there is no"
      echo "contract at that address on the chain. Run scripts/start_anvil.sh --bg"
      echo "FIRST (it redeploys, which changes the address), then start this stack."
      exit 1
    fi
  fi
fi


