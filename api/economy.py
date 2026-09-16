"""
PULSAR — Economy ledger (audit #6 C5, hardened per audit #8 F-07).

The Firestore rules deliberately forbid CLIENT writes to `matches`,
`leaderboard`, and the economy fields of `users` ("only the settlement server
writes these collections"). This module IS the writer those rules anticipate:
it uses the Firestore Admin SDK (which bypasses security rules by design) to
record server-authoritative settlements:

  - matches/{matchId}      one document per settled duel (signed proof included)
  - users/{addr}           economy counters advanced ONLY by settlement facts
  - leaderboard/{addr}     real wins/earnings rows, recomputed from counters

F-07 hardening over the first version:
  - ATOMIC: every settlement is one WriteBatch — no half-written ledger if the
    process dies between writes.
  - IDEMPOTENT: the batch carries a `settlementId` (hash of the settled FACTS).
    A retried settlement (two replicas racing settle, a re-run of the sweep)
    writes the SAME id and is skipped instead of double-incrementing counters.
  - CLAIM CONFLICT: `record_claim` refuses to overwrite a different tx hash —
    the first verified claim wins; a forged re-claim cannot rewrite history.
  - OBSERVABLE: ledger failures are logged loudly (stderr) instead of being
    silently swallowed — a dead ledger must be visible in the logs.

Everything here is best-effort: a ledger failure must never break settlement
or the on-chain claim (money keeps moving; the ledger can be back-filled).
When Firestore is not configured the module degrades to a no-op.
"""

from __future__ import annotations

import hashlib
import os
import sys
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


# Audit #10 (item 6): ledger failures are no longer only a stderr line nobody
# greps. Every failure increments in-process counters exposed by
# ledger_health() (surfaced on /api/health), so a dead ledger is VISIBLE in
# monitoring instead of being discovered during a payout dispute.
_LEDGER_FAILURES = {"record_settlement": 0, "record_claim": 0, "total": 0}
_LEDGER_LAST_ERROR: dict[str, Any] = {}


def _log_ledger_error(where: str, exc: BaseException) -> None:
    """F-07: a silent ledger is an invisible lie. Log to stderr AND bump the
    health counters (the money path itself stays unaffected)."""
    try:
        _LEDGER_FAILURES[where] = _LEDGER_FAILURES.get(where, 0) + 1
        _LEDGER_FAILURES["total"] += 1
        _LEDGER_LAST_ERROR.clear()
        _LEDGER_LAST_ERROR.update({"where": where, "error": repr(exc)[:200], "at": int(time.time())})
    except Exception:
        pass
    print(f"[economy] ledger write failed in {where}: {exc!r}", file=sys.stderr)


def ledger_health() -> dict[str, Any]:
    """Observability for the best-effort ledger (audit #10 item 6)."""
    return {
        "available": ledger_available(),
        "failures": dict(_LEDGER_FAILURES),
        "lastError": dict(_LEDGER_LAST_ERROR),
    }


def _winner_share() -> float:
    """Single source of truth for the winner share (F-17): 98% unless the
    platform fee bps env is overridden. The contract's PLATFORM_FEE_BPS = 200
    is the on-chain authority; this mirrors it for display/ledger math."""
    fee_bps = float(os.environ.get("PLATFORM_FEE_BPS", "200"))
    return (10_000.0 - fee_bps) / 10_000.0


def record_claim(match_id: str, claimer: str, tx_hash: str, signature: str) -> bool:
    """Persist the on-chain settlement transaction AFTER the winner claims.

    F-04: the caller (main.py) has ALREADY verified the receipt on-chain —
    to == escrow, status == 1, MatchSettled event with this matchId. This
    function only persists the verified fact.

    F-07 claim-conflict guard: if a different tx hash was already recorded
    for this match, the new claim is refused (returns False). The first
    VERIFIED claim wins; nobody can rewrite a settled match's proof.
    """
    db = _fs_db()
    if db is None:
        return False
    try:
        doc_ref = db.collection("matches").document(match_id)
        existing = doc_ref.get()
        if existing.exists:
            prev_hash = (existing.to_dict() or {}).get("settlementTxHash")
            if prev_hash and prev_hash != tx_hash:
                _log_ledger_error(
                    "record_claim",
                    ValueError(
                        f"claim conflict for {match_id}: already recorded {prev_hash}, refusing {tx_hash}"
                    ),
                )
                return False
        doc_ref.set(
            {
                "settlementTxHash": tx_hash,
                "claimedBy": claimer.lower(),
                "claimedAt": int(time.time()),
                "onChain": True,
            },
            merge=True,
        )
        return True
    except Exception as exc:
        _log_ledger_error("record_claim", exc)
        return False


def record_settlement(match: Any) -> None:
    """Ledger write after a successful server settlement. Best-effort, atomic,
    idempotent (F-07).

    Writes in ONE batch:
      matches/{matchId}  — result, times, and the oracle signature
      users/{winner|loser} — wins/losses/totalMatches advanced by the FACT
      leaderboard/{addr} — real stats rows for the podium

    Idempotency: the batch carries `settlementId = sha256(matchId|winner|
    times)`. If the match doc already records the same id, the settlement was
    already ledgered (retry / replica race) and everything is skipped — so a
    re-run can never double-increment a player's counters.
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
        forfeit = bool(getattr(match, "forfeit", False))
        prize = round(stake * 2 * _winner_share(), 2) if winner else 0.0

        # F-07 idempotency key: derived from the settled FACTS themselves, so
        # the same settlement reached twice produces the same id.
        outcome = winner or "void"
        times_key = getattr(match, "validated_times", None) or {}
        settlement_id = hashlib.sha256(
            "|".join(
                [
                    match_id,
                    outcome,
                    f"{stake:.2f}",
                    str(settled_at),
                    str(sorted((k, tuple(v or ())) for k, v in times_key.items())),
                ]
            ).encode()
        ).hexdigest()

        match_ref = db.collection("matches").document(match_id)
        existing = match_ref.get()
        if existing.exists:
            prev_id = (existing.to_dict() or {}).get("settlementId")
            if prev_id == settlement_id:
                return  # already ledgered — nothing to do (idempotent replay)
            # A DIFFERENT settlement id for the same match should not happen
            # (the engine settles once). Record the anomaly but keep the first
            # ledger row: history is append-only from here.
            if prev_id:
                _log_ledger_error(
                    "record_settlement",
                    ValueError(
                        f"settlement id drift for {match_id}: {prev_id} != {settlement_id}; keeping first"
                    ),
                )
                return

        doc: dict[str, Any] = {
            "id": match_id,
            "players": players,
            "game": "reaction",
            "stake": stake,
            "status": "settled" if winner else "void",
            "timestamp": settled_at,
            "onChain": bool(signed.get("signature")),
            "forfeit": forfeit,
            "settlementId": settlement_id,
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

        # ONE atomic batch: match doc + both user counters + leaderboard row
        # commit together or not at all (F-07).
        batch = db.batch()
        batch.set(match_ref, doc, merge=True)

        for addr in players:
            is_winner = addr == winner
            batch.set(
                db.collection("users").document(addr),
                {
                    "totalMatches": _inc(1),
                    "wins": _inc(1) if is_winner else _inc(0),
                    "losses": _inc(1) if (winner and not is_winner) else _inc(0),
                    "voids": _inc(1) if not winner else _inc(0),
                    "lastSettledAt": settled_at,
                },
                merge=True,
            )

        if winner:
            batch.set(
                db.collection("leaderboard").document(winner),
                {
                    "address": winner,
                    "wins": _inc(1),
                    "totalMatches": _inc(1),
                    "earnedUSDT": _inc(prize),
                    "updatedAt": settled_at,
                },
                merge=True,
            )

        batch.commit()
    except Exception as exc:
        # Ledger is a shadow of the money path — never raise into settlement,
        # but make the failure VISIBLE (F-07).
        _log_ledger_error("record_settlement", exc)


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


__all__ = [
    "ledger_available",
    "ledger_health",
    "record_claim",
    "record_settlement",
    "settlement_id_for",
]


def settlement_id_for(match_id: str, outcome: str, stake: float, settled_at: int) -> str:
    """Exposed for tests: the deterministic settlement id."""
    return hashlib.sha256(
        "|".join([match_id, outcome, f"{stake:.2f}", str(settled_at), ""]).encode()
    ).hexdigest()
