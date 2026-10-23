"""Bans and velocity limits (plan item 11.3 / G6).

Two different problems, and conflating them is how anti-abuse becomes
anti-player:

  * a **ban** is a decision about a person — an operator, with a reason, for a
    period. It must be auditable: who, why, until when.
  * a **velocity limit** is a decision about a PATTERN — too many duels started
    in too short a window. It is automatic, temporary, and must never be
    permanent, because a fast human and a bot look identical in a single sample.

So they are separate records with separate lifetimes, and the velocity limit is
deliberately generous: it exists to stop a script opening hundreds of duels, not
to slow down someone who is simply playing a lot tonight.

Defaults are "not banned, no velocity block", so nothing that exists today
changes behaviour.
"""
from __future__ import annotations

import os
from typing import Any

import backendmode
import timebase

COLLECTION = "pulsar_abuse"

# How many duels an address may START in the window before a cooldown.
VELOCITY_MAX_MATCHES = 20
VELOCITY_WINDOW_SECONDS = 10 * 60
# How long the automatic cooldown lasts once tripped. Short on purpose: this is
# a pattern check, not a punishment.
VELOCITY_COOLDOWN_SECONDS = 15 * 60

_CLIENT: Any = None
_CLIENT_RESOLVED = False


def _firestore_client() -> Any:
    """One client for the process lifetime — see api/eligibility.py."""
    # Audit H-18: `PULSAR_MATCH_STORE=memory` means this process must not depend
    # on Firestore. Obeying it here as well is what stops the launcher from
    # leaving a client pointed at an emulator that was never started (60 s of
    # blocked requests per call, reported as a dead test rather than a missing
    # dependency).
    if not backendmode.firestore_may_be_used():
        return None
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


class AbuseError(RuntimeError):
    """The address may not start a duel right now."""


class StoreUnavailable(AbuseError):
    """The abuse record could not be read (audit M-03).

    A SUBCLASS of AbuseError so an existing caller that only knows the old
    exception still refuses the duel — but the HTTP layer maps it to 503, not
    403, because "we cannot check" is not "you are banned" and the client should
    retry rather than show the player a suspension message.
    """


def _load(address: str) -> dict[str, Any]:
    """Read an abuse record, refusing to guess when the store cannot answer.

    Audit M-03 (2026-10-22): this used to fall through to the in-process map on
    a store error. An address that is not in that map resolves to "not banned",
    so a Firestore blip silently UNBANNED every player whose record lived on
    another replica or an earlier process — the one direction a ban must never
    fail. `api/limits.py` had the same bug and was fixed under H-02; this is the
    same fix, and the same reasoning: a control that opens when the database is
    unavailable is not a control.

    Memory mode (no client configured) still uses the local map, because there
    the map IS the source of truth.
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
                "Your account status could not be checked. Staked play is paused "
                "until the store is reachable — a suspension must never lift "
                "because a database is unavailable."
            ) from exc
    return dict(_memory.get(addr, {}))


def _save(address: str, data: dict[str, Any]) -> None:
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
        # A failed write here is NOT swallowed: an unrecorded ban would look
        # like a ban that was applied (the admin sees 200) while the offender
        # is free (audit M-03). The exception reaches the admin endpoint.
        client.collection(COLLECTION).document(addr).set(data)
    _memory[addr] = dict(data)


def state(address: str) -> dict[str, Any]:
    """The address's abuse state, with expired entries resolved away."""
    now = timebase.now()
    data = _load(address)
    banned_until = float(data.get("bannedUntil", 0) or 0)
    cooldown_until = float(data.get("velocityCooldownUntil", 0) or 0)
    starts = [float(t) for t in (data.get("recentStarts") or []) if now - float(t) <= VELOCITY_WINDOW_SECONDS]
    return {
        "banned": banned_until > now,
        "bannedUntil": banned_until,
        "banReason": data.get("banReason", ""),
        "velocityBlocked": cooldown_until > now,
        "velocityCooldownUntil": cooldown_until,
        "recentStarts": len(starts),
    }


def ban(address: str, seconds: int, reason: str) -> dict[str, Any]:
    """Ban an address. `reason` is REQUIRED — an unexplained ban is not auditable."""
    if not reason or not reason.strip():
        raise AbuseError("A ban must carry a reason")
    if seconds <= 0:
        raise AbuseError("A ban must have a positive duration")
    data = _load(address)
    data["bannedUntil"] = timebase.now() + seconds
    data["banReason"] = reason.strip()
    data["bannedAt"] = timebase.now()
    _save(address, data)
    return state(address)


def unban(address: str) -> dict[str, Any]:
    data = _load(address)
    data.pop("bannedUntil", None)
    data.pop("banReason", None)
    data.pop("bannedAt", None)
    _save(address, data)
    return state(address)


def note_start(address: str) -> None:
    """Record that `address` started a duel, and trip the cooldown if needed."""
    now = timebase.now()
    data = _load(address)
    starts = [float(t) for t in (data.get("recentStarts") or []) if now - float(t) <= VELOCITY_WINDOW_SECONDS]
    starts.append(now)
    data["recentStarts"] = starts
    if len(starts) >= VELOCITY_MAX_MATCHES:
        data["velocityCooldownUntil"] = now + VELOCITY_COOLDOWN_SECONDS
    _save(address, data)


def require(address: str) -> None:
    """Raise `AbuseError` when the address may not start a duel."""
    now = timebase.now()
    data = state(address)
    if data["banned"]:
        remaining = int(data["bannedUntil"] - now)
        raise AbuseError(
            f"This account is suspended for another {remaining // 3600}h. "
            f"Reason: {data['banReason']}. Contact support if you believe this is wrong."
        )
    if data["velocityBlocked"]:
        remaining = int(data["velocityCooldownUntil"] - now)
        raise AbuseError(
            f"Too many duels started in a short window — a {remaining // 60}-minute cooldown is in effect. "
            "Free Training is still available."
        )
