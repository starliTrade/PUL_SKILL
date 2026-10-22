"""Responsible-gaming limits (plan item 11.3 / G3).

A game holding real money needs three controls that exist for the PLAYER's sake,
not the house's:

  * a **deposit limit** — a ceiling the player sets on themselves;
  * **self-exclusion** — a period during which the player cannot stake at all;
  * a **cool-off** — a short, immediate pause for someone who wants to stop now.

Two design decisions worth stating, because they are the difference between a
control and a decoration:

  1. **A limit can be lowered at any time and raised only after a delay.** A
     limit a player can raise the moment they want to breach it is not a limit.
     Clearing it entirely is immediate — removing your own ceiling is not
     something to slow down.
  2. **Self-exclusion cannot be lifted early.** It is the one control that has to
     hold when the player most wants it not to.

Defaults are UNLIMITED, so nothing that exists today changes behaviour — the
controls only bind when a player opts into them.
"""
from __future__ import annotations

import os
from typing import Any

import timebase

COLLECTION = "pulsar_limits"

# Raising a limit takes effect after this long. Lowering and clearing are immediate.
RAISE_DELAY_SECONDS = 24 * 60 * 60
MIN_EXCLUSION_SECONDS = 24 * 60 * 60
MAX_EXCLUSION_SECONDS = 365 * 24 * 60 * 60
MAX_COOLOFF_SECONDS = 24 * 60 * 60

_CLIENT: Any = None
_CLIENT_RESOLVED = False


def _firestore_client() -> Any:
    """One client for the process lifetime — see api/eligibility.py."""
    global _CLIENT, _CLIENT_RESOLVED
    if _CLIENT_RESOLVED:
        return _CLIENT
    _CLIENT_RESOLVED = True
    try:
        from google.cloud import firestore as _firestore  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    project = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT")
    if not os.environ.get("FIRESTORE_EMULATOR_HOST") and not project:
        return None
    try:
        _CLIENT = _firestore.Client(project=project)
    except Exception:  # noqa: BLE001
        _CLIENT = None
    return _CLIENT


_memory: dict[str, dict[str, Any]] = {}


class LimitError(RuntimeError):
    """The player may not stake right now, or the change is not allowed yet."""


class StoreUnavailable(LimitError):
    """The controls could not be read. Fail CLOSED — see `_load`."""


def _load(address: str) -> dict[str, Any]:
    """Read a player's controls.

    Audit H-02 (2026-10-22): this used to fall through to the in-process map on
    a store error, and an address absent from that map resolves to "no limits" —
    so a transient Firestore outage silently LIFTED every self-exclusion and
    every deposit ceiling for players whose record lived on another replica or
    an earlier process. In a money product that is the wrong direction to fail:
    a control that opens when the database is unavailable is not a control.

    A configured client that cannot answer now raises `LimitError`, which the
    HTTP layer turns into a refusal. Memory mode (no client) keeps the local
    map, because there the map IS the source of truth.
    """
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
        try:
            snap = client.collection(COLLECTION).document(addr).get()
            if snap.exists:
                return dict(snap.to_dict() or {})
            return {}
        except Exception as exc:  # noqa: BLE001
            raise StoreUnavailable(
                "Your responsible-gaming controls could not be read. Staked play "
                "is paused until the store is reachable — this is deliberate: a "
                "limit must never disappear because a database is unavailable."
            ) from exc
    return dict(_memory.get(addr, {}))


def _save(address: str, data: dict[str, Any]) -> None:
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
        client.collection(COLLECTION).document(addr).set(data)
    _memory[addr] = dict(data)


def _resolved(data: dict[str, Any], now: float) -> tuple[float | None, float | None]:
    """(effective limit, pending limit) at `now`.

    Audit M-01 (2026-10-22): `state()` used to PERSIST the matured pending raise
    as a side effect — a GET wrote to the database, and two replicas could
    resolve the same pending value concurrently. The effective value is a pure
    function of the stored document and the clock, so it is computed here and
    only written by the endpoint that actually changes the limit.
    """
    current = data.get("depositLimit")
    pending = data.get("pendingLimit")
    pending_at = float(data.get("pendingLimitAt", 0) or 0)
    if pending is not None and now >= pending_at:
        return float(pending), None
    return (None if current is None else float(current)), (None if pending is None else float(pending))


def state(address: str) -> dict[str, Any]:
    """The player's controls, with the effective values resolved."""
    now = timebase.now()
    data = _load(address)
    limit, pending = _resolved(data, now)
    exclusion_until = float(data.get("excludedUntil", 0) or 0)
    cooloff_until = float(data.get("cooloffUntil", 0) or 0)
    return {
        "depositLimit": limit,
        # M-02: the name is a historical label. What is enforced is a ceiling on
        # ONE duel's stake, not a cumulative deposit total; say so in the payload
        # so no client (or operator) can read it as the stronger control.
        "enforcedAs": "maxStakePerDuel",
        "pendingLimit": pending,
        "pendingLimitAt": data.get("pendingLimitAt") if pending is not None else None,
        "excludedUntil": exclusion_until,
        "cooloffUntil": cooloff_until,
        "selfExcluded": exclusion_until > now,
        "coolingOff": cooloff_until > now,
    }


def set_deposit_limit(address: str, limit: float | None) -> dict[str, Any]:
    """Set a deposit ceiling. Lowering and clearing are immediate; raising waits."""
    now = timebase.now()
    data = _load(address)
    current = data.get("depositLimit")
    if limit is not None and limit <= 0:
        raise LimitError("A deposit limit must be greater than zero")
    # Clearing a limit is NOT raising it: removing your own ceiling is not
    # something to slow down. Only an actual increase waits.
    raising = current is not None and limit is not None and limit > float(current)
    if raising:
        data["pendingLimit"] = limit
        data["pendingLimitAt"] = now + RAISE_DELAY_SECONDS
    else:
        data["depositLimit"] = limit
        data.pop("pendingLimit", None)
        data.pop("pendingLimitAt", None)
    _save(address, data)
    return state(address)


def self_exclude(address: str, seconds: int) -> dict[str, Any]:
    """Exclude the player from staked play for `seconds`. Cannot be lifted early."""
    if seconds < MIN_EXCLUSION_SECONDS:
        raise LimitError(f"Self-exclusion must be at least {MIN_EXCLUSION_SECONDS // 3600} hours")
    if seconds > MAX_EXCLUSION_SECONDS:
        raise LimitError("Self-exclusion cannot exceed one year")
    data = _load(address)
    now = timebase.now()
    # Audit H-01 (2026-10-22): this used to OVERWRITE `excludedUntil`, so a
    # player who had excluded themselves for a year could call the endpoint
    # again with 24 hours and shorten their own exclusion. The UI promises the
    # opposite ("cannot be lifted early"), and an exclusion a player can shorten
    # the moment they regret it is not a control. Only a LONGER period applies.
    current = float(data.get("excludedUntil", 0) or 0)
    data["excludedUntil"] = max(current, now + seconds)
    _save(address, data)
    return state(address)


def cool_off(address: str, seconds: int) -> dict[str, Any]:
    """A short, immediate pause. The player can come back when it expires."""
    if seconds <= 0 or seconds > MAX_COOLOFF_SECONDS:
        raise LimitError(f"A cool-off must be between 1 second and {MAX_COOLOFF_SECONDS // 3600} hours")
    data = _load(address)
    now = timebase.now()
    # Same direction rule as self-exclusion: a cool-off may be extended, never
    # shortened (setting a new 1-second pause must not cut a 24-hour one).
    current = float(data.get("cooloffUntil", 0) or 0)
    data["cooloffUntil"] = max(current, now + seconds)
    _save(address, data)
    return state(address)


def require(address: str, stake: float) -> None:
    """Raise `LimitError` when the player's own controls forbid this stake."""
    now = timebase.now()
    data = state(address)
    if data["excludedUntil"] > now:
        remaining = int(data["excludedUntil"] - now)
        raise LimitError(
            f"You have self-excluded from staked play. It cannot be lifted early; "
            f"{remaining // 3600}h remaining. Free Training is still available."
        )
    if data["cooloffUntil"] > now:
        remaining = int(data["cooloffUntil"] - now)
        raise LimitError(
            f"You are in a cool-off for another {remaining}s. Free Training is still available."
        )
    limit = data.get("depositLimit")
    if limit is not None and stake > float(limit):
        raise LimitError(
            f"This stake ({stake:g} USDT) is above your own deposit limit ({float(limit):g} USDT). "
            "Lower the stake, or raise the limit — which takes effect after a delay."
        )
