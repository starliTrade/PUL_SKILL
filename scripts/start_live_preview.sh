#!/usr/bin/env bash
# Live preview: a URL you can open and actually play on.
#
# The E2E stack runs on 127.0.0.1, which is reachable from THIS machine and from
# nowhere else. A preview needs three things wired together, and missing any one
# of them produces a page that loads and then does nothing:
#
#   1. the API exposed on its own public URL;
#   2. the FRONTEND built with VITE_GAME_SERVER_URL pointing at that API URL —
#      otherwise the app runs in "server not configured" mode and only practice
#      works;
#   3. the API told to accept BOTH origins (CORS) and the tunnel hostname
#      (TrustedHost), or every request is refused before it reaches a handler.
#
# Usage: scripts/start_live_preview.sh [--stop]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CF="${CLOUDFLARED:-/tmp/cloudflared}"
API_PORT="${PULSAR_E2E_API_PORT:-8000}"
FRONTEND_PORT="${PULSAR_E2E_FRONTEND_PORT:-3000}"
RUN_DIR="/tmp/pulsar-preview"
mkdir -p "$RUN_DIR"

stop_all() {
  for f in "$RUN_DIR"/*.pid; do
    [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null
    rm -f "$f"
  done
  bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
  pkill -f "vite.*${FRONTEND_PORT}" 2>/dev/null || true
  echo "live preview stopped"
}

if [[ "${1:-}" == "--stop" ]]; then stop_all; exit 0; fi

if [[ ! -x "$CF" ]]; then
  echo "cloudflared not found at $CF (set CLOUDFLARED=/path/to/cloudflared)" >&2
  exit 1
fi

# --- 0. the emulator and anvil must be UP, not merely configured ---------------
#
# Audit 2026-10-15: the chaos suite KILLS the emulator and anvil as part of its
# scenarios, and nothing restarts them. The API then starts happily, `/api/health`
# returns 200 (it does not touch Firestore), and every real request fails with
# `ValueError: The transaction has no transaction ID, so it cannot be rolled
# back.` — which reads like a code bug and is a dead dependency. Check the
# dependencies themselves, not a health endpoint that does not cover them.
if ! curl -sf -o /dev/null -m 3 "http://127.0.0.1:${PULSAR_FIRESTORE_PORT:-8081}/" 2>/dev/null; then
  echo "emulator is down — starting it"
  bash "$ROOT/scripts/start_emulator.sh" --bg >/dev/null 2>&1 || true
  sleep 3
fi
if ! curl -sf -o /dev/null -m 3 -X POST -H "Content-Type: application/json" \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
    "http://127.0.0.1:${PULSAR_ANVIL_PORT:-8545}" 2>/dev/null; then
  echo "anvil is down — starting it"
  PATH="$PATH:/root/workspace/.foundry/bin" bash "$ROOT/scripts/start_anvil.sh" --bg >/dev/null 2>&1 || true
  sleep 2
fi

# --- 1. the local stack (emulator + anvil + API) ------------------------------
bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
sleep 2
bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1 || { echo "the E2E stack did not start" >&2; exit 1; }

# --- 2. expose the API, learn its URL ----------------------------------------
"$CF" tunnel --url "http://127.0.0.1:${API_PORT}" --no-autoupdate \
  > "$RUN_DIR/api-tunnel.log" 2>&1 &
echo $! > "$RUN_DIR/api-tunnel.pid"

API_URL=""
for _ in $(seq 1 60); do
  API_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$RUN_DIR/api-tunnel.log" 2>/dev/null | head -1)"
  [[ -n "$API_URL" ]] && break
  sleep 1
done
if [[ -z "$API_URL" ]]; then
  echo "could not get an API tunnel URL — see $RUN_DIR/api-tunnel.log" >&2
  stop_all
  exit 1
fi
echo "API  -> $API_URL"

# --- 3. frontend, built against the PUBLIC api url ---------------------------
cd "$ROOT"
VITE_GAME_SERVER_URL="$API_URL" \
VITE_CHAIN_ID=31337 \
  bunx vite --host 127.0.0.1 --port "$FRONTEND_PORT" > "$RUN_DIR/vite.log" 2>&1 &
echo $! > "$RUN_DIR/vite.pid"
for _ in $(seq 1 40); do
  curl -sf -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/" && break
  sleep 1
done

"$CF" tunnel --url "http://127.0.0.1:${FRONTEND_PORT}" --no-autoupdate \
  > "$RUN_DIR/frontend-tunnel.log" 2>&1 &
echo $! > "$RUN_DIR/frontend-tunnel.pid"

FRONTEND_URL=""
for _ in $(seq 1 60); do
  FRONTEND_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$RUN_DIR/frontend-tunnel.log" 2>/dev/null | head -1)"
  [[ -n "$FRONTEND_URL" ]] && break
  sleep 1
done
if [[ -z "$FRONTEND_URL" ]]; then
  echo "could not get a frontend tunnel URL — see $RUN_DIR/frontend-tunnel.log" >&2
  stop_all
  exit 1
fi

# --- 4. restart the API knowing BOTH public origins ---------------------------
#
# CORS takes EXACT origins — no wildcards — so the frontend's URL has to be known
# before the API starts, which is why this comes last. TrustedHost needs the API's
# own tunnel hostname, or every request is refused before a handler sees it.
API_HOST="$(echo "$API_URL" | sed -E 's#https://##')"
FRONTEND_HOST="$(echo "$FRONTEND_URL" | sed -E 's#https://##')"
bash "$ROOT/scripts/start_e2e_stack.sh" --stop >/dev/null 2>&1 || true
sleep 2
CORS_ALLOW_ORIGINS="http://127.0.0.1:${FRONTEND_PORT},http://localhost:${FRONTEND_PORT},${FRONTEND_URL}" \
ALLOWED_HOSTS="127.0.0.1,localhost,${API_HOST},${FRONTEND_HOST}" \
  bash "$ROOT/scripts/start_e2e_stack.sh" >/dev/null 2>&1 || { echo "the API did not restart" >&2; exit 1; }

echo
echo "================================================================"
echo "  PLAY HERE:  $FRONTEND_URL"
echo "  API:        $API_URL"
echo "================================================================"
echo
echo "Notes:"
echo "  * Practice mode works with no wallet. For the staked duel you need a"
echo "    browser wallet pointed at chain 31337 (the local anvil)."
echo "  * If trycloudflare is blocked from your network, say so — the fallback"
echo "    is a different tunnel provider, not a different app."
echo "  * Stop with: scripts/start_live_preview.sh --stop"
