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
import sys
from typing import Any

import timebase
import xp as xp_engine


def _fs_db() -> Any:
    """The Firestore client the ACTIVE store is using, or None in memory mode.

    Audit CRITICAL-1: this used to read `getattr(store, "_fs_store", None)` (and
    a `store.store` fallback that is also never set) — module attributes that do
    not exist, because `_fs_store` is an INSTANCE attribute of
    DurableMatchStore. In production the ledger therefore never wrote anything:
    no wins, no XP, no prize, no leaderboard row. `store.durable_db()` is the
    ONE definition of this resolution.
    """
    try:
        import store as _store  # local import avoids a circular import

        return _store.durable_db()
    except Exception:
        pass
    return None


def _firestore_module() -> Any:
    """The google.cloud.firestore MODULE (for the @transactional decorator).

    `store._firestore` is a DurableMatchStore instance attribute holding a
    Client, which has no `transactional` — the same trap audit C1 hit.
    """
    try:
        from google.cloud import firestore as _fs  # type: ignore[attr-defined]  # noqa: PLC0415

        return _fs
    except Exception:  # pragma: no cover - SDK absent
        return None


def ledger_configured() -> bool:
    """Whether a durable client was constructed — a CONFIG check."""
    return _fs_db() is not None


def ledger_available() -> bool:
    """Whether the ledger is USABLE — a config check, and named as one.

    Audit 2026-10-13 (found by the phase-10 chaos suite): this was surfaced on
    `/api/health` as `available`, which reads like a reachability probe. It is
    not: it answers "was a client constructed", so a dead Firestore still
    reported `available: true`.

    A real reachability probe was tried and REVERTED: a Firestore read inside a
    health check hangs when the backend is down (the client retries far longer
    than a liveness probe may take), and a hanging probe gets the container
    killed — worse than the lie. The honest signal is `failures`, which
    increments on an actual ledger failure (`_log_ledger_error`).
    """
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
        _LEDGER_LAST_ERROR.update({"where": where, "error": repr(exc)[:200], "at": int(timebase.now())})
    except Exception:
        pass
    print(f"[economy] ledger write failed in {where}: {exc!r}", file=sys.stderr)


def ledger_health() -> dict[str, Any]:
    """Observability for the best-effort ledger (audit #10 item 6)."""
    return {
        # `configured` is the config check; `available` is kept as its alias
        # for existing dashboards, and `failures` is the signal that actually
        # moves when the ledger breaks.
        "available": ledger_available(),
        "configured": ledger_configured(),
        "failures": dict(_LEDGER_FAILURES),
        "lastError": dict(_LEDGER_LAST_ERROR),
        # Audit H-14: a growing queue is the alert; `oldestAgeSeconds` says how
        # long a player's statistics have been wrong.
        "outbox": dict(OUTBOX_STATE),
    }


# --- the ledger outbox (audit H-14, 2026-10-22) -------------------------------
#
# A settlement was already final on-chain when the ledger write failed: the
# winner has the money, but wins/XP/leaderboard never advanced. The only signal
# was a counter on /api/health — accurate, and useless at 3 a.m., because
# nothing ever tried again. A player's history therefore diverged from the chain
# permanently.
#
# Every failed settlement is now queued in `pulsar_ledger_outbox`. The existing
# sweep in main.py drains the queue, `record_settlement` is idempotent through
# its `settlements/{id}` gate, so a retry can only ever apply the settlement
# once. Health reports how far behind the queue is — a number that grows is the
# alert condition.
OUTBOX = "pulsar_ledger_outbox"
OUTBOX_STATE: dict[str, Any] = {
    "pending": 0,
    "oldestAgeSeconds": 0,
    "lastDrainAt": 0,
    "drained": 0,
    "failed": 0,
}


def _enqueue_outbox(match_id: str, error: str) -> bool:
    """Queue a settlement the ledger did not manage to write. Never raises."""
    db = _fs_db()
    if db is None or not match_id:
        return False
    try:
        db.collection(OUTBOX).document(match_id).set(
            {
                "matchId": match_id,
                "status": "pending",
                "lastError": error[:300],
                "at": int(timebase.now()),
            }
        )
        OUTBOX_STATE["pending"] = int(OUTBOX_STATE.get("pending", 0)) + 1
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[economy] outbox enqueue failed: {exc!r}", file=sys.stderr)
        return False


def drain_outbox(store: Any, limit: int = 20) -> dict[str, Any]:
    """Retry queued settlements. Idempotent by construction.

    `store` is the match store, which is the only place that can rebuild the
    `Match` object the ledger needs to read.
    """
    db = _fs_db()
    if db is None:
        return dict(OUTBOX_STATE)

    processed = failed = 0
    try:
        pending = list(
            db.collection(OUTBOX)
            .where("status", "==", "pending")
            .order_by("at")
            .limit(limit)
            .stream()
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[economy] outbox read failed: {exc!r}", file=sys.stderr)
        return dict(OUTBOX_STATE)

    oldest = 0
    for snap in pending:
        row = snap.to_dict() or {}
        match_id = str(row.get("matchId", ""))
        oldest = max(oldest, int(timebase.now()) - int(row.get("at", 0) or 0))
        try:
            match = store.get(match_id)
        except Exception:  # noqa: BLE001 - the match may not exist here
            failed += 1
            _bump_outbox(snap.reference, row, "match not found on this replica")
            continue
        outcome = record_settlement(match)
        if outcome == "failed":
            failed += 1
            _bump_outbox(snap.reference, row, "ledger retry failed")
            continue
        processed += 1
        try:
            snap.reference.delete()
        except Exception as exc:  # noqa: BLE001
            print(f"[economy] outbox cleanup failed: {exc!r}", file=sys.stderr)

    OUTBOX_STATE.update(
        {
            "pending": max(0, len(pending) - processed),
            "oldestAgeSeconds": oldest,
            "lastDrainAt": int(timebase.now()),
            "drained": int(OUTBOX_STATE.get("drained", 0)) + processed,
            "failed": int(OUTBOX_STATE.get("failed", 0)) + failed,
        }
    )
    return dict(OUTBOX_STATE)


def _bump_outbox(ref: Any, row: dict[str, Any], error: str) -> None:
    try:
        ref.set(
            {
                "attempts": int(row.get("attempts", 0) or 0) + 1,
                "lastError": error[:300],
            },
            merge=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[economy] outbox attempt update failed: {exc!r}", file=sys.stderr)


def player_stats(address: str) -> dict[str, Any] | None:
    """A player's server-authoritative progression (audit M31).

    Returns None when the ledger is unavailable — the caller must say so rather
    than report zeros, which would read as a real (and wrong) "you have never
    won a duel".
    """
    db = _fs_db()
    if db is None:
        return None
    try:
        snap = db.collection("users").document(address.lower()).get()
        if not snap.exists:
            # No row means NO RECORD, not "zero wins". Reporting zeros as
            # authoritative would let the client overwrite a real local
            # progression with 0/level 1 — the exact confusion this contract
            # exists to prevent. The caller falls back to its local estimate.
            return None
        d = snap.to_dict() or {}
        return {
            "wins": int(d.get("wins", 0) or 0),
            "losses": int(d.get("losses", 0) or 0),
            "voids": int(d.get("voids", 0) or 0),
            "totalMatches": int(d.get("totalMatches", 0) or 0),
            "xp": float(d.get("xp", 0) or 0),
            "level": int(d.get("level", 1) or 1),
            "winStreak": int(d.get("winStreak", 0) or 0),
            "bestReactionMs": float(d.get("bestReactionMs", 0) or 0),
            "avgReactionMs": float(d.get("avgReactionMs", 0) or 0),
            # Audit M31: the XP this player's last settlement awarded, so the
            # post-match screen can show the server's number instead of a
            # client-side estimate.
            "lastXpAwarded": float(d.get("lastXpAwarded", 0) or 0),
        }
    except Exception as exc:
        _log_ledger_error("player_stats", exc)
        return None


# Audit M20: the contract's PLATFORM_FEE_BPS is the ON-CHAIN AUTHORITY — it is
# what actually splits the money. This used to read the env, so an override made
# the server's ledger disagree with the chain and a player's recorded prize
# differed from what they received. The value is pinned to the Solidity source
# by `tests/unit/test_economy_and_oracle_ids.py`.
CONTRACT_PLATFORM_FEE_BPS = 200


def _winner_share() -> float:
    """The winner share the CONTRACT pays (audit M20). Not env-overridable."""
    return (10_000.0 - CONTRACT_PLATFORM_FEE_BPS) / 10_000.0


def prize_in_units(stake_units: int, decimals: int = 6) -> int:
    """The winner's prize in BASE UNITS (audit M21).

    Integer arithmetic throughout: the pool is `2 * stake`, the fee is taken in
    base units, and the remainder is the prize — exactly what the contract does
    with its own integer math. Float arithmetic (`round(stake * 2 * share, 2)`)
    can differ by a base unit, so the ledger would record a number the chain
    never paid.
    """
    if stake_units <= 0:
        return 0
    pool = 2 * stake_units
    fee = (pool * CONTRACT_PLATFORM_FEE_BPS) // 10_000
    return pool - fee


def record_claim(match_id: str, claimer: str, tx_hash: str) -> bool:
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
        # Audit H3 (closure review): this was a read-then-write — `doc_ref.get()`
        # outside any transaction, then `set()`. Two concurrent claims with
        # different tx hashes both passed the conflict check, both returned
        # True, and the last write silently won. The documented invariant
        # ("the first VERIFIED claim wins") was not enforced. Same class as H3
        # in record_settlement, three lines above.
        transactional = getattr(_firestore_module(), "transactional", None)
        if transactional is None:
            raise RuntimeError("google-cloud-firestore is required for the economy ledger")

        def _apply(tx: Any) -> bool:
            existing = doc_ref.get(transaction=tx)
            if existing.exists:
                prev_hash = (existing.to_dict() or {}).get("settlementTxHash")
                if prev_hash and prev_hash != tx_hash:
                    _log_ledger_error(
                        "record_claim",
                        ValueError(
                            f"claim conflict for {match_id}: already recorded "
                            f"{prev_hash}, refusing {tx_hash}"
                        ),
                    )
                    return False
            tx.set(
                doc_ref,
                {
                    "settlementTxHash": tx_hash,
                    "claimedBy": claimer.lower(),
                    "claimedAt": int(timebase.now()),
                    "onChain": True,
                },
                merge=True,
            )
            return True

        return transactional(_apply)(db.transaction())
    except Exception as exc:
        _log_ledger_error("record_claim", exc)
        return False


def record_settlement(match: Any) -> str:
    """Ledger write after a successful server settlement. Best-effort, atomic,
    idempotent (F-07).

    Writes in ONE batch:
      matches/{matchId}  — result, times, and the oracle signature
      users/{winner|loser} — wins/losses/totalMatches advanced by the FACT
      leaderboard/{addr} — real stats rows for the podium

    A failure is queued in `pulsar_ledger_outbox` and retried by the sweep
    (audit H-14) — the settlement is already final on-chain, so "give up and
    log" means a permanent divergence between the chain and the player's stats.

    The settled facts are read from the ORACLE-SIGNED envelope
    (`match.signed_settlement`), which mirrors engine.settle()'s result:
    `validatedTimes {addr: [ms, ...]}` and `forfeits {addr: bool}`.

    Idempotency: the batch carries `settlementId = sha256(matchId|winner|
    times)`. If the match doc already records the same id, the settlement was
    already ledgered (retry / replica race) and everything is skipped — so a
    re-run can never double-increment a player's counters.
    Void matches are recorded (totalMatches only) so histories stay truthful.

    Returns "written" | "skipped" | "unavailable" | "failed" (audit H-14). The
    caller uses it to decide whether the settlement needs a retry, and a failure
    is queued in the outbox so a later sweep can apply it.
    """
    db = _fs_db()
    if db is None:
        return "unavailable"
    try:
        winner = (getattr(match, "winner", "") or "").lower()
        players = [a.lower() for a in (getattr(match, "players", {}) or {})]
        stake = float(getattr(match, "stake", 0.0) or 0.0)
        settled_at = int(getattr(match, "settled_at", 0) or timebase.now())
        signed = getattr(match, "signed_settlement", None) or {}
        match_id = getattr(match, "match_id", "")
        # Audit #11 C1: the Match dataclass has NO `forfeit` or
        # `validated_times` attributes — reading them via getattr() silently
        # produced forfeit=False and an empty idempotency key for EVERY
        # settlement. The truth lives in the signed envelope (engine.settle's
        # result, mirrored by _attach_signed_envelope):
        #   validatedTimes {addr: [ms, ...]}, forfeits {addr: bool}.
        packet = signed if isinstance(signed, dict) else {}
        raw_times = packet.get("validatedTimes", {}) or {}
        validated_times: dict[str, list[float]] = {
            a: [float(t) for t in (raw_times.get(a) or []) if isinstance(t, int | float)]
            for a in players
        }
        forfeit = any(bool(v) for v in (packet.get("forfeits", {}) or {}).values())
        # Audit M21: computed in base units, exactly like the contract.
        prize_units = prize_in_units(int(round(stake * 10**6)), 6) if winner else 0
        prize = prize_units / 10**6

        # F-07 idempotency key: derived from the settled FACTS themselves, so
        # the same settlement reached twice produces the same id.
        outcome = winner or "void"
        # Audit #11 C1: the key hashes the REAL validated times (was: a
        # nonexistent attribute → always ""), so idempotency is per-FACT.
        settlement_id = _settlement_id(match_id, outcome, stake, settled_at, validated_times)

        match_ref = db.collection("matches").document(match_id)
        # Audit H3: the idempotency gate used to be a plain `match_ref.get()`
        # OUTSIDE any transaction, followed by a batch commit. Two replicas (or
        # the two call sites in main.py) could both observe "no row yet" and
        # both commit, double-counting wins / totalMatches / earnedUSDT for one
        # duel. A read-then-write is not a mutex; a transaction is.
        gate_ref = db.collection("settlements").document(settlement_id)

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
            # Audit #11 C1: reaction times come from the signed packet's
            # validatedTimes (was: match.players misread as rounds — always []).
            doc["reactionTimes"] = {a: list(validated_times.get(a, [])) for a in players}

        # ONE atomic transaction: the gate, the match doc, both user counters
        # and the leaderboard row commit together or not at all. Firestore
        # retries a conflicting transaction, so the loser of the race re-reads
        # the gate, finds it present, and returns without touching a counter.
        transactional = getattr(_firestore_module(), "transactional", None)
        if transactional is None:
            raise RuntimeError("google-cloud-firestore is required for the economy ledger")

        def _apply(tx: Any) -> bool:
            gate = gate_ref.get(transaction=tx)
            if gate.exists:
                return False  # another replica already ledgered this settlement

            existing = match_ref.get(transaction=tx)
            if existing.exists:
                prev_id = (existing.to_dict() or {}).get("settlementId")
                if prev_id == settlement_id:
                    return False  # idempotent replay
                if prev_id:
                    # A DIFFERENT settlement id for the same match should not
                    # happen (the engine settles once). Keep the first ledger
                    # row: history is append-only from here.
                    _log_ledger_error(
                        "record_settlement",
                        ValueError(
                            f"settlement id drift for {match_id}: {prev_id} != "
                            f"{settlement_id}; keeping first"
                        ),
                    )
                    return False

            # Audit M31: read the committed progression. Firestore requires
            # EVERY read to precede EVERY write in a transaction — putting this
            # after the first `tx.set` fails the whole settlement with
            # ReadAfterWriteError (caught by the emulator test, not by the
            # memory-mode unit tests).
            prior: dict[str, dict[str, Any]] = {}
            for addr in players:
                usnap = db.collection("users").document(addr).get(transaction=tx)
                prior[addr] = (usnap.to_dict() or {}) if usnap.exists else {}
            progression = {
                addr: _progression_fields(
                    addr, prior.get(addr) or {}, winner, stake, list(validated_times.get(addr, []))
                )
                for addr in players
            }

            tx.set(gate_ref, {"matchId": match_id, "settlementId": settlement_id, "at": settled_at})
            tx.set(match_ref, doc, merge=True)

            for addr in players:
                is_winner = addr == winner
                tx.set(
                    db.collection("users").document(addr),
                    {
                        "totalMatches": _inc(1),
                        "wins": _inc(1) if is_winner else _inc(0),
                        "losses": _inc(1) if (winner and not is_winner) else _inc(0),
                        "voids": _inc(1) if not winner else _inc(0),
                        "lastSettledAt": settled_at,
                        **progression[addr],
                    },
                    merge=True,
                )

            if winner:
                tx.set(
                    db.collection("leaderboard").document(winner),
                    {
                        "address": winner,
                        "wins": _inc(1),
                        "totalMatches": _inc(1),
                        "earnedUSDT": _inc(prize),
                        # Audit M31: the podium shows the same server-computed
                        # progression the profile does.
                        "xp": progression[winner]["xp"],
                        "level": progression[winner]["level"],
                        # Audit 2026-10-13: the client read `totalEarnedUSDT` and
                        # a reaction time that were NEVER written here, so every
                        # podium row showed a computed guess (`wins * 1.96`) and
                        # a hardcoded 185ms. Write the real fields.
                        "bestReactionMs": progression[winner]["bestReactionMs"],
                        "updatedAt": settled_at,
                    },
                    merge=True,
                )
            return True

        wrote = bool(transactional(_apply)(db.transaction()))
        if not wrote:
            return "skipped"
        return "written"
    except Exception as exc:
        # Ledger is a shadow of the money path — never raise into settlement,
        # but make the failure VISIBLE and RETRYABLE (F-07, H-14).
        _log_ledger_error("record_settlement", exc)
        _enqueue_outbox(str(getattr(match, "match_id", "")), repr(exc)[:300])
        return "failed"


def _progression_fields(
    addr: str,
    before: dict[str, Any],
    winner: str,
    stake: float,
    times: list[float],
) -> dict[str, Any]:
    """The server-authoritative progression fields for one player (audit M31).

    `before` is the committed user document, read INSIDE the settlement
    transaction, so XP and the streak are derived from state the server owns —
    never from a client claim. `times` are the player's validated round times
    for this match (the ledger's own record, not a client number).
    """
    is_winner = bool(winner) and addr == winner
    prior_streak = int(before.get("winStreak", 0) or 0)
    if not winner:
        # A void is not a defeat: it neither extends nor breaks a streak.
        streak = prior_streak
    elif is_winner:
        streak = prior_streak + 1
    else:
        streak = 0

    matches_before = int(before.get("totalMatches", 0) or 0)
    # Audit 2026-10-13: a forfeited side is recorded with the sentinel
    # FORFEIT_SENTINEL_MS (0) so the signed arrays stay non-empty. Folding that
    # 0 into the running average dragged a forfeiting player's avgReactionMs
    # toward zero — a statistic that looked like a measurement and was not one.
    real_times = [t for t in times if t > 0]
    sample = (sum(real_times) / len(real_times)) if real_times else 0.0

    best = float(before.get("bestReactionMs", 0) or 0)
    for t in real_times:
        if best == 0 or t < best:
            best = t

    # Audit H-15 (2026-10-22): the denominator was `totalMatches`, which also
    # counts voids and forfeits — matches that contribute no reaction sample.
    # Every void therefore diluted a player's average toward zero, so a stat
    # that looked like a measurement drifted whenever they were abandoned or
    # the match voided. The denominator must be the number of SAMPLE-BEARING
    # matches, tracked separately.
    avg_before = float(before.get("avgReactionMs", 0) or 0)
    samples_before = int(before.get("reactionSamples", 0) or 0)
    if samples_before <= 0 and avg_before > 0:
        # Legacy documents: best available estimate of how many samples the old
        # average was built from. Never zero when an average exists.
        samples_before = max(1, matches_before)
    avg: float
    sample_count: int
    if real_times:
        total_before = avg_before * samples_before
        avg = round((total_before + sample) / (samples_before + 1))
        sample_count = samples_before + 1
    else:
        avg = avg_before
        sample_count = samples_before

    xp_before = float(before.get("xp", 0) or 0)
    outcome = "win" if is_winner else ("loss" if winner else "void")
    summary = xp_engine.match_xp(outcome, stake, sample, xp_before, streak)

    return {
        "xp": summary["newTotalXP"],
        "level": summary["newLevel"],
        "winStreak": streak,
        "bestReactionMs": best,
        "avgReactionMs": avg,
        "reactionSamples": sample_count,
        "lastXpAwarded": summary["totalAwardedXP"],
    }


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
    "player_stats",
    "record_claim",
    "record_settlement",
    "settlement_id_for",
]


def _settlement_id(
    match_id: str,
    outcome: str,
    stake: float,
    settled_at: int,
    times: dict[str, list[float]] | None = None,
) -> str:
    """The deterministic idempotency key for one settled duel.

    Audit H5: this is the ONE definition. It used to exist twice — production
    hashed the validated times while the exported test helper hashed an empty
    string in that slot, so a test that used the helper to prove idempotency
    passed no matter what the ledger did.
    """
    return hashlib.sha256(
        "|".join(
            [
                match_id,
                outcome,
                f"{stake:.2f}",
                str(settled_at),
                str(sorted((k, tuple(v or ())) for k, v in (times or {}).items())),
            ]
        ).encode()
    ).hexdigest()


def settlement_id_for(
    match_id: str,
    outcome: str,
    stake: float,
    settled_at: int,
    times: dict[str, list[float]] | None = None,
) -> str:
    """Exposed for tests: the deterministic settlement id.

    Takes the same facts production hashes, so a test using it is comparing
    against reality rather than against a second, divergent implementation.
    """
    return _settlement_id(match_id, outcome, stake, settled_at, times)
