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


def _load(address: str) -> dict[str, Any]:
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
        try:
            snap = client.collection(COLLECTION).document(addr).get()
            if snap.exists:
                return dict(snap.to_dict() or {})
        except Exception:  # noqa: BLE001
            # A store outage must not LIFT a ban. Fall through to the local
            # record; an unknown address is not banned, which is the documented
            # default rather than a guess.
            pass
    return dict(_memory.get(addr, {}))


def _save(address: str, data: dict[str, Any]) -> None:
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
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
