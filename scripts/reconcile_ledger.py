#!/usr/bin/env python3
"""PULSAR ledger reconciliation (audit H-14 follow-through, 2026-10-22).

The ledger is a SHADOW of the chain: `record_settlement` counts wins, losses and
matches from the signed envelopes. When a write failed (before the outbox
existed) the shadow stopped matching reality, and nothing could tell you by how
much. `/api/health` reports that writes failed; this tool reports what the
numbers should be.

WHAT IT DOES
------------
Reads every document in `matches` with a `settlementId` (i.e. every match the
ledger has recorded) and recomputes, per address:

    totalMatches = count(matches containing the address)
    wins         = count(match.winner == address)
    losses       = count(address played, a winner exists, address != winner)
    voids        = count(matches containing the address with no winner)

then compares with `users/{address}` and prints the drift. It is READ-ONLY:
there is no `--fix`. Deliberate — an automatic "repair" of money-adjacent
counters is a second bug waiting to happen, and the outbox is the mechanism for
applying a settlement that did not land. This tool's job is to tell you whether
you need it.

USAGE
-----
    python scripts/reconcile_ledger.py                 # human-readable report
    python scripts/reconcile_ledger.py --json          # machine-readable
    python scripts/reconcile_ledger.py --limit 5000    # cap the scan

Exit code: 0 when no drift, 1 when drift is found (usable as a cron alert),
2 when the durable store is not reachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))


def expected_counters(match_docs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Recompute per-address counters from the recorded matches.

    Pure function: the whole point is that it can be tested and reasoned about
    without a database, and that its definition of a win is the same one the
    engine uses (winner present, address == winner).
    """
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {"totalMatches": 0, "wins": 0, "losses": 0, "voids": 0}
    )
    for doc in match_docs:
        players = [str(p).lower() for p in (doc.get("players") or [])]
        if not players:
            continue
        winner = str(doc.get("winner") or "").lower()
        for addr in players:
            row = out[addr]
            row["totalMatches"] += 1
            if not winner:
                row["voids"] += 1
            elif addr == winner:
                row["wins"] += 1
            else:
                row["losses"] += 1
    return dict(out)


def compare(
    expected: dict[str, dict[str, int]],
    actual: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The drift rows. Missing user documents count as zero (never played)."""
    drift: list[dict[str, Any]] = []
    for addr, want in sorted(expected.items()):
        have = actual.get(addr) or {}
        row: dict[str, Any] = {"address": addr, "drift": {}}
        for field, value in want.items():
            recorded = int(have.get(field, 0) or 0)
            if recorded != value:
                row["drift"][field] = {"ledger": recorded, "matches": value}
        if row["drift"]:
            drift.append(row)
    return drift


def _db() -> Any:
    import store as store_module

    db = store_module.durable_db()
    if db is None:
        print(
            "The durable store is not configured (PULSAR_MATCH_STORE / Firestore "
            "credentials). Reconciliation needs the ledger's own database.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile the PULSAR ledger")
    parser.add_argument("--limit", type=int, default=5000, help="max match documents to scan")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    db = _db()
    matches: list[dict[str, Any]] = []
    for snap in db.collection("matches").limit(args.limit).stream():
        doc = snap.to_dict() or {}
        if doc.get("settlementId"):  # only reconciled settlements
            matches.append(doc)

    expected = expected_counters(matches)

    actual: dict[str, dict[str, Any]] = {}
    for addr in expected:
        snap = db.collection("users").document(addr).get()
        if snap.exists:
            actual[addr] = snap.to_dict() or {}

    drift = compare(expected, actual)

    if args.json:
        print(json.dumps({"matches": len(matches), "drift": drift}, indent=2))
    else:
        print(f"scanned {len(matches)} recorded settlements, {len(expected)} players")
        if not drift:
            print("no drift: the ledger matches the recorded settlements")
        for row in drift:
            fields = ", ".join(
                f"{name} ledger={d['ledger']} expected={d['matches']}"
                for name, d in row["drift"].items()
            )
            print(f"  {row['address']}: {fields}")
        print(
            "\nThis tool never writes. A settlement that did not land is retried "
            "from pulsar_ledger_outbox by the server sweep; if the outbox is "
            "empty and drift exists, the failure predates the outbox."
        )
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
