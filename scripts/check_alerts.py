"""Evaluate the server's health against alert thresholds (plan item 11.2).

The metrics existed and nothing watched them. For a game holding real money that
is the largest operational hole there is: a dead oracle means winners cannot
claim, and without an alert the only signal is a player complaining.

Design notes, because they are the whole point:

  * It exits **non-zero** when something is wrong, so any scheduler can run it —
    cron, a k8s liveness probe, a CI job, a human. No vendor is required for the
    check to work.
  * A webhook is **optional** (`PULSAR_ALERT_WEBHOOK`): if it is set, the alert
    is POSTed there too. If it is not, the exit code is still the signal.
  * Thresholds are named constants with the reason next to them, so changing one
    is a decision rather than a guess.

Usage:
    .venv/bin/python scripts/check_alerts.py [--url http://127.0.0.1:8000]
Exit codes: 0 healthy, 1 warning, 2 critical, 3 unreachable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# --- thresholds ---------------------------------------------------------------
# A dead RPC or ledger is CRITICAL: rounds fail closed and money stops moving.
# Signature failures are CRITICAL because a winner who cannot get a signed
# settlement cannot claim — the stake is stuck until the refund window.
CRITICAL = "CRITICAL"
WARNING = "WARNING"

# p95 above this is a player-visible stall. The local emulator sits in the tens
# of seconds under load (documented in LOAD-REPORT.md), so this is tuned for a
# real deployment, not for the emulator.
P95_WARN_MS = 2000.0
# Any sustained contention means the store is at capacity.
CONTENTION_WARN = 50


def _get(url: str, path: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path)
    req.add_header("Host", "127.0.0.1:8000")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read() or b"{}")


def evaluate(health: dict, metrics: dict) -> list[tuple[str, str]]:
    """Return [(severity, message)]. Pure, so it is testable without a server."""
    out: list[tuple[str, str]] = []

    rpc = health.get("rpc") or {}
    if rpc.get("configured") and not rpc.get("reachable"):
        out.append((CRITICAL, "RPC is unreachable — rounds fail closed, no duel can start"))

    ledger = health.get("ledger") or {}
    if ledger.get("configured") and not ledger.get("available"):
        out.append((CRITICAL, "ledger is unavailable — settlements cannot be recorded"))
    failures = (ledger.get("failures") or {}).get("total", 0)
    if failures:
        out.append((WARNING, f"ledger has {failures} failed writes"))

    sweep = health.get("sweep") or {}
    sweep_failures = (sweep.get("failures") or {}).get("total", 0)
    if sweep_failures:
        out.append((WARNING, f"the sweep has failed {sweep_failures} times — stuck matches may not settle"))

    sig = metrics.get("signatures") or {}
    if sig.get("failed"):
        out.append(
            (CRITICAL, f"{sig['failed']} settlement signatures failed — winners cannot claim")
        )

    store = metrics.get("store") or {}
    contention = store.get("contention503", 0)
    if contention >= CONTENTION_WARN:
        out.append((WARNING, f"{contention} requests were refused for store contention"))

    for route, entry in (metrics.get("endpoints") or {}).items():
        p95 = entry.get("p95Ms")
        if p95 is not None and p95 > P95_WARN_MS:
            out.append((WARNING, f"{route} p95 is {p95}ms (threshold {P95_WARN_MS}ms)"))

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("PULSAR_ALERT_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        health = _get(args.url, "/api/health")
        metrics = _get(args.url, "/api/metrics")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"CRITICAL: the server is unreachable at {args.url}: {exc}", file=sys.stderr)
        return 3

    alerts = evaluate(health, metrics)
    if not alerts:
        if not args.quiet:
            print("healthy: no alert thresholds crossed")
        return 0

    worst = CRITICAL if any(sev == CRITICAL for sev, _ in alerts) else WARNING
    for severity, message in alerts:
        print(f"{severity}: {message}")

    webhook = os.environ.get("PULSAR_ALERT_WEBHOOK", "").strip()
    if webhook:
        payload = json.dumps({"worst": worst, "alerts": [f"{s}: {m}" for s, m in alerts]}).encode()
        try:
            req = urllib.request.Request(webhook, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as exc:  # noqa: BLE001
            # A failed notification must not change the verdict: the exit code is
            # the signal of record, the webhook is a convenience.
            print(f"WARNING: could not POST to the alert webhook: {exc}", file=sys.stderr)

    return 2 if worst == CRITICAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
