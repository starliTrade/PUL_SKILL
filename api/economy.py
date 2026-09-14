"""
PULSAR — Economy ledger (audit #6, C5).

The Firestore rules deliberately forbid CLIENT writes to `matches`,
`leaderboard`, and the economy fields of `users` ("only the settlement server
writes these collections") — correct security, but until now the settlement
server never wrote them either, so the leaderboard was permanently empty and
every client sync was silently rejected by the rules.

This module IS the writer those rules anticipate: it uses the Firestore Admin
SDK (which bypasses security rules by design) to record server-authoritative
settlements:

  - matches/{matchId}      one document per settled duel (signed proof included)
  - users/{addr}           economy counters advanced ONLY by settlement facts
  - leaderboard/{addr}     real wins/earnings rows, recomputed from counters

Everything here is best-effort: a ledger failure must never break settlement
or the on-chain claim (money keeps moving; the ledger can be back-filled).
When Firestore is not configured the module degrades to a no-op.
"""

from __future__ import annotations

import os
import time
from typing import Any


def _fs_db() -> Any:
    """The Firestore client from the store, or None in memory mode."""
    try:
        import store as _store  # local import avoids a circular import

        fs = getattr(_store, "_fs_store", None) or getattr(
            getattr(_store, "store", None), "_fs_store", None
        )
        if fs is not None:
            return fs.db
    except Exception:
        pass
    return None


def ledger_available() -> bool:
    return _fs_db() is not None


def record_claim(match_id: str, claimer: str, tx_hash: str, signature: str) -> bool:
    """Persist the on-chain settlement transaction AFTER the winner claims.

    This closes the 'certificate can never be on-chain' gap (audit #6 P2):
    the tx hash exists only in the winner's browser until it lands here, so
    every duel's certificate previously rendered 'LOCAL RESULT · NOT ON-CHAIN'
    even for genuinely settled duels.
    """
    db = _fs_db()
    if db is None:
        return False
    try:
        db.collection("matches").document(match_id).set(
            {
                "settlementTxHash": tx_hash,
                "claimedBy": claimer.lower(),
                "claimedAt": int(time.time()),
                "onChain": True,
            },
            merge=True,
        )
        return True
    except Exception:
        return False


def record_settlement(match: Any) -> None:
    """Ledger write after a successful server settlement. Best-effort.

    Writes in one pass:
      matches/{matchId}  — result, times, and the oracle signature
      users/{winner|loser} — wins/losses/totalMatches advanced by the FACT
      leaderboard/{addr} — real stats rows for the podium
    Void matches are recorded (totalMatches only) so histories stay truthful.
    """
    db = _fs_db()
    if db is None:
        return
    try:
        winner = (getattr(match, "winner", "") or "").lower()
        players = [a.lower() for a in (getattr(match, "players", {}) or {})]
        stake = float(getattr(match, "stake", 0.0) or 0.0)
        settled_at = int(getattr(match, "settled_at", 0) or time.time())
        signed = getattr(match, "signed_settlement", None) or {}
        match_id = getattr(match, "match_id", "")
        prize = round(stake * 2 * 0.98, 2) if winner else 0.0

        # 1. Match document — server-authored, signed, replayable.
        doc: dict[str, Any] = {
            "id": match_id,
            "players": players,
            "game": "reaction",
            "stake": stake,
            "status": "settled" if winner else "void",
            "timestamp": settled_at,
            "onChain": bool(signed.get("signature")),
        }
        if winner:
            doc.update(
                {
                    "winner": winner,
                    "prize": prize,
                    "oracleSignature": signed.get("signature", ""),
                }
            )
            times = getattr(match, "players", {}) or {}
            doc["reactionTimes"] = {
                a: [
                    r.get("result_ms")
                    for r in ((times.get(a) or {}).get("rounds") or {}).values()
                    if isinstance(r, dict) and r.get("result_ms")
                ]
                for a in players
            }
        db.collection("matches").document(match_id).set(doc, merge=True)

        # 2. User economy counters — advanced by SETTLEMENT FACTS only.
        for addr in players:
            is_winner = addr == winner
            db.collection("users").document(addr).set(
                {
                    "totalMatches": _inc(1),
                    "wins": _inc(1) if is_winner else _inc(0),
                    "losses": _inc(1) if (winner and not is_winner) else _inc(0),
                    "voids": _inc(1) if not winner else _inc(0),
                    "lastSettledAt": settled_at,
                },
                merge=True,
            )

        # 3. Leaderboard rows from the same facts (real earnings, labeled).
        if winner:
            db.collection("leaderboard").document(winner).set(
                {
                    "address": winner,
                    "wins": _inc(1),
                    "totalMatches": _inc(1),
                    "earnedUSDT": _inc(prize),
                    "updatedAt": settled_at,
                },
                merge=True,
            )
    except Exception:
        # Ledger is a shadow of the money path — never raise into settlement.
        pass


def _inc(n: float) -> dict[str, Any]:
    """Firestore FieldValue.increment, duck-typed so unit tests without the
    SDK still exercise the code path (falls back to a plain marker)."""
    try:
        from google.cloud.firestore_v1.base_value import FieldValue  # type: ignore

        return FieldValue.increment(n)
    except Exception:
        try:
            from google.cloud import firestore as _gcf  # type: ignore

            return _gcf.Increment(n)
        except Exception:
            return {"__increment__": n}


__all__ = ["ledger_available", "record_claim", "record_settlement"]
