"""Server-side integrity scoring (audit C-02a, 2026-10-22).

WHY THIS EXISTS
---------------
A script that answers a revealed target in ~110 ms beats a human (~250 ms) every
round. The server's hard floor (`MIN_HUMAN_MS`) stops the absurd cases, and the
server-observed reaction time (`observed_ms`) stops a client from *claiming* a
fast time it did not achieve — but a real script on a fast connection waits
110 ms and answers honestly-fast. Nothing in the product looked at the SHAPE of a
player's times, which is where a machine is obvious:

  - humans cluster far above the floor; scripts hug it,
  - human reaction times vary by 15–25 % between rounds; scripts are metronomic,
  - humans rarely repeat a value to 0.1 ms.

WHAT IT DOES, AND WHAT IT DOES NOT
----------------------------------
This is DETECTION, not proof. It cannot tell a fast human with an unusual
profile from a slow bot; that is why it never voids a match, never changes a
payout and never bans an account. It computes a suspicion score from the
server-observed times, and above the threshold it files an entry in the operator
review queue (`pulsar_review`) with the evidence. A human decides.

Any product that auto-penalised on a statistical score would, at these sample
counts, punish real players — and the audit's own finding was that unverifiable
"anti-cheat" claims are worse than no claim at all. The honest position: the
timing floor is enforced; suspicious profiles are surfaced.

NOT A REPLACEMENT FOR: KYC/withdrawal limits (C-02c, a product decision) and a
real anti-bot (device attestation) — see the audit.
"""

from __future__ import annotations

import os
import statistics
import threading
from collections.abc import Sequence
from typing import Any

MIN_HUMAN_MS = 105.0          # MUST match match_engine.MIN_HUMAN_MS
FLOOR_GAP_MS = 25.0           # "hugging the floor" = within this of the minimum
MIN_SAMPLES = 6               # below this, no judgement is made at all
MAX_SAMPLES = 40              # rolling window per account
FLAG_AT = 0.8                 # suspicion at/above this files a review entry

COLLECTION = "pulsar_integrity"
REVIEW = "pulsar_review"

# How long a READ may take before the caller gets an answer anyway (audit L-04).
#
# `open_reviews` streams a Firestore query. The SDK's default retry policy turns
# an unreachable database into a request that never returns: measured on this
# checkout, `/api/health` hung for >120 s with the emulator down, so a liveness
# probe would kill a healthy container during a Firestore incident and restart
# it into the same outage. A health answer that is slightly stale beats no
# answer at all — and the timeout is REPORTED, not silently swallowed.
HEALTH_READ_TIMEOUT = float(os.environ.get("PULSAR_HEALTH_READ_TIMEOUT", "1.5"))
ADMIN_READ_TIMEOUT = float(os.environ.get("PULSAR_ADMIN_READ_TIMEOUT", "10"))

_health_read_error = ""

# The liveness path never waits on the database (audit L-04).
#
# Measured on this checkout with `FIRESTORE_EMULATOR_HOST` pointing at a dead
# port: `Query.stream(timeout=1.5)` — and even `retry=None` — never returned.
# The SDK blocks while establishing the channel, and a per-call deadline does
# not reach that. So `/api/health` cannot rely on a timeout to be fast: it must
# not perform the read itself.
#
# One daemon thread performs the read and caches the answer. The thread is a
# daemon so a stuck read can never block interpreter shutdown, and the
# `inFlight` flag means at most ONE is ever outstanding per process — a stuck
# read costs one thread, not one per probe.
_health_lock = threading.Lock()
_health_state: dict[str, Any] = {"open": None, "error": "", "inFlight": False, "reads": 0}


def _read_reviews_in_background() -> None:
    try:
        rows = open_reviews(limit=50, timeout=HEALTH_READ_TIMEOUT)
        with _health_lock:
            _health_state["open"] = len(rows)
            _health_state["error"] = ""
            _health_state["reads"] = int(_health_state["reads"]) + 1
    except Exception as exc:  # noqa: BLE001
        with _health_lock:
            _health_state["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    finally:
        with _health_lock:
            _health_state["inFlight"] = False


def _kick_health_read() -> None:
    with _health_lock:
        if _health_state["inFlight"]:
            return
        _health_state["inFlight"] = True
    try:
        threading.Thread(
            target=_read_reviews_in_background, name="pulsar-health-read", daemon=True
        ).start()
    except Exception:  # noqa: BLE001 — threading can fail under exotic limits
        with _health_lock:
            _health_state["inFlight"] = False

# In-memory fallback (tests, and dev without Firestore). Keyed by address.
_memory: dict[str, list[float]] = {}
_reviews: list[dict[str, Any]] = []
_write_failures = 0


def _client() -> Any:
    """The Firestore client of the ACTIVE store, or None (never raises).

    Imported lazily: `store` imports `match_engine`, which refuses to import
    without ORACLE_SIGNING_SECRET. A module-level import would make this scoring
    module unimportable in a test that only wants the maths.
    """
    try:
        import store as _store_mod

        return _store_mod.durable_db()
    except Exception:  # noqa: BLE001 - no store configured is a normal state
        return None


def score(times: Sequence[float]) -> dict[str, Any]:
    """Suspicion 0..1 for a sequence of SERVER-OBSERVED reaction times.

    Deterministic and explainable: every point of the score has a reason string
    an operator can read, and a reviewer can disagree with.
    """
    values = [float(t) for t in times if t and float(t) > 0]
    n = len(values)
    if n < MIN_SAMPLES:
        return {
            "suspicion": 0.0,
            # Never judge on a sample this small: a human who happened to be
            # quick twice is not evidence, and flagging on it trains operators
            # to ignore the queue.
            "reasons": [],
            "samples": n,
            "enoughEvidence": False,
        }

    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    cv = (stdev / mean) if mean else 0.0
    median = statistics.median(values)
    near_floor = sum(1 for v in values if v <= MIN_HUMAN_MS + FLOOR_GAP_MS)
    floor_ratio = near_floor / n
    repeats = max((values.count(v) for v in set(values)), default=0)

    suspicion = 0.0
    reasons: list[str] = []

    if floor_ratio > 0.5:
        # 60 % of the samples inside 25 ms of a 105 ms floor is not a person.
        worth = min(0.6, (floor_ratio - 0.5) / 0.5 * 0.6)
        suspicion += worth
        reasons.append(
            f"{near_floor}/{n} rounds within {FLOOR_GAP_MS:.0f}ms of the "
            f"{MIN_HUMAN_MS:.0f}ms floor"
        )

    if cv < 0.10:
        worth = min(0.5, (0.10 - cv) / 0.10 * 0.5)
        suspicion += worth
        reasons.append(f"reaction times vary by only {cv * 100:.1f}% (human: 15-25%)")

    if median <= MIN_HUMAN_MS + 30:
        suspicion += 0.5
        reasons.append(f"median reaction {median:.0f}ms is at the human floor")

    if repeats >= 3:
        suspicion += 0.4
        reasons.append(f"the same time to 0.1ms repeated {repeats} times")

    return {
        "suspicion": round(min(1.0, suspicion), 3),
        "reasons": reasons,
        "samples": n,
        "enoughEvidence": True,
        "stats": {
            "meanMs": round(mean, 1),
            "medianMs": round(median, 1),
            "stdevMs": round(stdev, 1),
            "variationPct": round(cv * 100, 1),
            "nearFloor": near_floor,
        },
    }


def _load(address: str) -> list[float]:
    db = _client()
    if db is not None:
        try:
            snap = db.collection(COLLECTION).document(address.lower()).get()
            if snap.exists:
                raw = (snap.to_dict() or {}).get("times") or []
                return [float(t) for t in raw][-MAX_SAMPLES:]
        except Exception as exc:  # noqa: BLE001
            print(f"[integrity] durable read failed: {exc!r}")
    return list(_memory.get(address.lower(), []))[-MAX_SAMPLES:]


def _save(address: str, times: list[float]) -> None:
    global _write_failures
    _memory[address.lower()] = times[-MAX_SAMPLES:]
    db = _client()
    if db is None:
        return
    try:
        db.collection(COLLECTION).document(address.lower()).set(
            {"times": times[-MAX_SAMPLES:], "updatedAt": __import__("time").time()},
            merge=True,
        )
    except Exception as exc:  # noqa: BLE001
        _write_failures += 1
        # Non-fatal by design: scoring is advisory. It must never break a round.
        print(f"[integrity] durable write failed: {exc!r}")


def observe(address: str, times: Sequence[float], match_id: str = "") -> dict[str, Any]:
    """Record a player's observed times and file a review entry when flagged."""
    global _write_failures
    history = _load(address)
    history.extend(float(t) for t in times if t and float(t) > 0)
    history = history[-MAX_SAMPLES:]
    _save(address, history)

    result = score(history)
    result["flagged"] = result["suspicion"] >= FLAG_AT
    if not result["flagged"]:
        return result

    # ONE open entry per account. Without this, every subsequent round files
    # another copy of the same flag — a queue that spams itself is a queue
    # operators stop reading (found by a test: 3 entries for 3 rounds).
    if _has_open_review(address):
        return result

    entry = {
        "address": address.lower(),
        "matchId": match_id,
        "suspicion": result["suspicion"],
        "reasons": result["reasons"],
        "stats": result.get("stats", {}),
        "times": history[-12:],
        "status": "open",
    }
    _reviews.append(entry)
    db = _client()
    if db is not None:
        try:
            db.collection(REVIEW).add(entry)
        except Exception as exc:  # noqa: BLE001
            _write_failures += 1
            print(f"[integrity] review write failed: {exc!r}")
    return result


def _has_open_review(address: str) -> bool:
    addr = address.lower()
    if any(r.get("address") == addr and r.get("status") == "open" for r in _reviews):
        return True
    db = _client()
    if db is None:
        return False
    try:
        for _snap in (
            db.collection(REVIEW)
            .where("address", "==", addr)
            .where("status", "==", "open")
            .limit(1)
            .stream()
        ):
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[integrity] review dedupe check failed: {exc!r}")
    return False


def open_reviews(limit: int = 50, *, timeout: float | None = ADMIN_READ_TIMEOUT) -> list[dict[str, Any]]:
    """The operator queue: durable first (another replica's flags), cache second.

    `timeout` is passed to the stream so a database that cannot answer produces
    an exception this function already handles, instead of blocking the caller
    forever. Callers that serve a liveness probe pass a short one (see
    `health()`); the operator UI can afford the default.
    """
    global _health_read_error
    out: list[dict[str, Any]] = []
    db = _client()
    if db is not None:
        try:
            for snap in (
                db.collection(REVIEW)
                .where("status", "==", "open")
                .limit(limit)
                .stream(timeout=timeout)
            ):
                row = dict(snap.to_dict() or {})
                row["id"] = snap.id
                out.append(row)
            _health_read_error = ""
        except Exception as exc:  # noqa: BLE001
            _health_read_error = f"{type(exc).__name__}: {str(exc)[:120]}"
            print(f"[integrity] review read failed: {exc!r}")
    if out:
        return out
    return [dict(r) for r in _reviews if r.get("status") == "open"][-limit:]


def resolve(review_id: str, status: str = "resolved", note: str = "") -> bool:
    """Close a review entry (operator decision). Returns False if not found."""
    if status not in ("resolved", "dismissed"):
        raise ValueError("status must be 'resolved' or 'dismissed'")
    found = False
    db = _client()
    if db is not None and review_id:
        try:
            ref = db.collection(REVIEW).document(review_id)
            if ref.get().exists:
                ref.set({"status": status, "note": note[:500]}, merge=True)
                found = True
        except Exception as exc:  # noqa: BLE001
            print(f"[integrity] review update failed: {exc!r}")
    for row in _reviews:
        if row.get("id") == review_id or (
            review_id and row.get("address") == review_id
        ):
            row["status"] = status
            found = True
    return found


def health() -> dict[str, Any]:
    """Never blocks. This is the body of `/api/health`, which a probe waits on.

    Before this, an unreachable Firestore made the endpoint hang (>120 s
    measured), which turns a database incident into a restart loop: the probe
    times out, the orchestrator kills a process that was serving fine, and the
    new one hangs in the same place.

    So the review count is CACHED: this call kicks a background read (at most
    one outstanding) and returns whatever is known now. `readStatus` says which
    of the three truths you are looking at — memory, a cached number, or nothing
    yet — because "0 open" and "could not ask" must not look the same.
    """
    if _client() is None:
        return {
            "flagThreshold": FLAG_AT,
            "minSamples": MIN_SAMPLES,
            "writeFailures": _write_failures,
            "openReviews": len([r for r in _reviews if r.get("status") == "open"]),
            "readStatus": "memory",
            "readError": "",
            "readTimeoutSeconds": HEALTH_READ_TIMEOUT,
        }
    _kick_health_read()
    with _health_lock:
        cached = _health_state["open"]
        error = _health_state["error"]
        in_flight = _health_state["inFlight"]
    return {
        "flagThreshold": FLAG_AT,
        "minSamples": MIN_SAMPLES,
        "writeFailures": _write_failures,
        "openReviews": cached,
        # "pending" on the first call after boot, "stale" once a cached read
        # exists, "ok" when the last read succeeded.
        "readStatus": ("ok" if cached is not None and not error else "stale")
        if cached is not None
        else "pending",
        "readInFlight": in_flight,
        "readError": error,
        "readTimeoutSeconds": HEALTH_READ_TIMEOUT,
    }
