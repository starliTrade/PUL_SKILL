#!/usr/bin/env python3
"""Mint a pool of real session tokens for the load profile (audit L-06).

WHY THIS EXISTS
---------------
The load test needs one distinct player per virtual user: `/api/queue` is rate
limited at 40 requests/minute PER ADDRESS, so 1000 virtual users sharing ten
tokens measures the limiter, not the queue. The SIWE handshake cannot produce
them fast enough — `/api/auth/verify` allows 30 verifications per minute per IP,
so 1000 players would take ~33 minutes of wall clock before the run even starts.

This tool mints the SAME tokens the handshake would (same code path:
`auth.issue_session`, same secret), one per throwaway address. It skips ONLY the
signature round-trip, which the run does not measure. Every token still has to
pass the server's own verification on every request — nothing is bypassed at
request time.

    ORACLE_SIGNING_SECRET=… python scripts/load_sessions.py --count 1000 \
        --out /tmp/pulsar-load-tokens.json

Then:

    PULSAR_LOAD_TOKENS=/tmp/pulsar-load-tokens.json \
        locust -f load/locustfile.py --headless -u 1000 -r 100 -t 45s
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--out", default="/tmp/pulsar-load-tokens.json")
    args = parser.parse_args()

    if not os.environ.get("ORACLE_SIGNING_SECRET"):
        print("ORACLE_SIGNING_SECRET must match the server's value", file=sys.stderr)
        return 2

    import auth  # noqa: PLC0415 — needs the secret in the environment first

    rng = random.Random(0)  # deterministic addresses: a rerun is comparable
    rows = []
    for _ in range(args.count):
        address = "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(40))
        rows.append({"address": address, "token": auth.issue_session(address)})

    Path(args.out).write_text(json.dumps(rows))
    print(f"wrote {len(rows)} sessions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
