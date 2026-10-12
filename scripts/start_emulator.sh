#!/usr/bin/env bash
# PULSAR — start the Firestore emulator for local/integration testing (plan item 0.7).
#
# Why this exists: `scripts/test_firestore_integration.py` SKIPS without
# credentials, so every Firestore-path bug (audit C1, H3, H4) shipped unseen.
# The emulator turns that skip into a real run — locally and in CI.
#
# Usage:
#   scripts/start_emulator.sh          # foreground (Ctrl-C to stop)
#   scripts/start_emulator.sh --bg     # background, writes the PID file
#   scripts/start_emulator.sh --stop   # stop a background instance
#
# Then run tests with:
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 GCLOUD_PROJECT=demo-pulsar pytest
set -euo pipefail

HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8081}"
PORT="${HOST##*:}"
BIND="${HOST%%:*}"
EMULATOR_VERSION="1.19.8"
JAR="${PULSAR_EMULATOR_JAR:-/root/workspace/.tools/firestore/firestore-emulator.jar}"
PIDFILE="/tmp/pulsar-firestore-emulator.pid"
URL="https://storage.googleapis.com/firebase-preview-drop/emulator/cloud-firestore-emulator-v${EMULATOR_VERSION}.jar"

find_java() {
  if command -v java >/dev/null 2>&1; then echo java; return; fi
  # Sandbox fallback: a standalone Temurin JRE unpacked under .tools/.
  local jre
  jre="$(ls -d /root/workspace/.tools/jdk-*/bin/java 2>/dev/null | head -1 || true)"
  if [[ -n "$jre" ]]; then echo "$jre"; return; fi
  echo "ERROR: no java runtime found. Install a JRE (the emulator is a Java app)." >&2
  exit 1
}

case "${1:-}" in
  --stop)
    if [[ -f "$PIDFILE" ]]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "stopped"
    else
      echo "no background emulator recorded"
    fi
    exit 0
    ;;
esac

JAVA="$(find_java)"

if [[ ! -f "$JAR" ]]; then
  echo "downloading Firestore emulator v${EMULATOR_VERSION}…"
  mkdir -p "$(dirname "$JAR")"
  curl -sSL -o "$JAR" "$URL"
fi

if curl -sf -o /dev/null "http://${HOST}/" 2>/dev/null; then
  echo "emulator already running on ${HOST}"
  exit 0
fi

if [[ "${1:-}" == "--bg" ]]; then
  nohup "$JAVA" -jar "$JAR" --host="$BIND" --port="$PORT" >/tmp/pulsar-firestore-emulator.log 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null "http://${HOST}/" && { echo "emulator up on ${HOST} (pid $(cat "$PIDFILE"))"; exit 0; }
    sleep 1
  done
  echo "emulator failed to start; see /tmp/pulsar-firestore-emulator.log" >&2
  exit 1
fi

echo "starting emulator on ${HOST} (Ctrl-C to stop)…"
exec "$JAVA" -jar "$JAR" --host="$BIND" --port="$PORT"
