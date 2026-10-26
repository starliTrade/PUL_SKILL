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
# H-19, second form: the jar used to default to `/root/workspace/.tools/...`,
# a directory that exists in the audit sandbox and nowhere else. In CI the
# `mkdir -p` below failed, `set -e` exited 1, and `verify.sh` — which starts this
# with `|| true` — carried on. The emulator gate then SKIPPED, the Playwright
# stack refused to start in firestore mode, and the E2E gate failed with zero
# tests run: three symptoms, one unwritable path. A cache directory is writable
# on every machine and is the right place for a downloaded artifact.
CACHE_DIR="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}"
JAR="${PULSAR_EMULATOR_JAR:-$CACHE_DIR/pulsar/firestore-emulator-v${EMULATOR_VERSION}.jar}"
# Keep the sandbox's pre-downloaded copy when it is there (it costs nothing and
# saves a 60 MB download); it is a fallback now, not the default.
if [[ ! -f "$JAR" && -z "${PULSAR_EMULATOR_JAR:-}" \
      && -f /root/workspace/.tools/firestore/firestore-emulator.jar ]]; then
  JAR=/root/workspace/.tools/firestore/firestore-emulator.jar
fi
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
