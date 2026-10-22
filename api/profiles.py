"""The player's own profile: display tag and saved friends (audit H-05).

Background. The client used to persist the profile by writing Firestore
`users/{address}` directly. `firestore.rules` denies every client write (the
ledger owns that document), so the write failed on every save and the failure was
swallowed by `console.warn`. Two consequences, both silent:

  * a player's tag and friend list never survived a browser;
  * worse, once the settlement ledger created `users/{address}`, the next
    `loadUserDataAsync` returned that document — which has no `savedFriends` —
    and the local list was replaced by nothing.

The profile is not economy data: it has no value to a cheater and belongs to
the player. It therefore lives in its OWN collection written by the server on
the player's behalf, authenticated by the same SIWE session as everything else.
`users/*` stays ledger-only, which is what makes the rules simple enough to be
correct.

Validation is deliberately strict: a saved friend is an ADDRESS (never a free
text field), the list is bounded, and a player cannot add themselves.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

COLLECTION = "pulsar_profiles"
MAX_FRIENDS = 100
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TAG = re.compile(r"^[A-Za-z0-9_]{3,20}$")

# Memory fallback so the feature works in memory mode and under tests.
_memory: dict[str, dict[str, Any]] = {}


class ProfileError(ValueError):
    """The caller sent a profile the server will not store."""


def _clean_tag(raw: Any) -> str:
    tag = str(raw or "").strip()
    if not tag:
        return ""
    if not _TAG.match(tag):
        raise ProfileError("A display tag must be 3-20 letters, numbers or underscores")
    return tag


def _clean_friends(raw: Any, *, strict: bool = True) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, Iterable) or isinstance(raw, str | bytes):
        if strict:
            raise ProfileError("savedFriends must be a list of addresses")
        return []
    out: list[str] = []
    for entry in raw:
        addr = str(entry or "").strip().lower()
        if not _ADDRESS.match(addr):
            if strict:
                raise ProfileError(f"Not a valid address: {addr[:12]}")
            continue
        if addr not in out:
            out.append(addr)
        if len(out) > MAX_FRIENDS:
            if strict:
                raise ProfileError(f"A profile can save at most {MAX_FRIENDS} friends")
            break
    return out


def _client() -> Any:
    """The Firestore client, or None in memory mode.

    Imported lazily: `store` imports the match engine, which requires the oracle
    secret at import time — importing this module must not drag that in (a
    standalone tool that only reads profiles should not need signing keys).
    """
    try:
        import store as store_module

        return store_module.durable_db()
    except Exception:  # noqa: BLE001 — no store configured is a normal mode
        return None


def get(address: str) -> dict[str, Any]:
    """The stored profile, or the empty profile for an address with none.

    A read failure is reported by raising: the caller must not silently replace
    a player's friend list with an empty one because the database blinked.
    """
    addr = address.lower()
    client = _client()
    if client is not None:
        snap = client.collection(COLLECTION).document(addr).get()
        data = dict(snap.to_dict() or {}) if snap.exists else {}
    else:
        data = dict(_memory.get(addr, {}))
    return {
        "address": addr,
        "playerId": str(data.get("playerId", "") or ""),
        "savedFriends": _clean_friends(data.get("savedFriends", []), strict=False),
        "updatedAt": data.get("updatedAt"),
    }


def update(
    address: str,
    *,
    player_id: Any = None,
    saved_friends: Any = None,
) -> dict[str, Any]:
    """Merge a profile change. Omitted fields are left alone.

    `player_id=None` means "do not change it"; an explicit empty string clears
    the display override and falls back to the generated tag.
    """
    addr = address.lower()
    current = get(addr)
    patch: dict[str, Any] = {}
    if player_id is not None:
        patch["playerId"] = _clean_tag(player_id)
    if saved_friends is not None:
        friends = _clean_friends(saved_friends)
        if addr in friends:
            raise ProfileError("You cannot save yourself as a friend")
        patch["savedFriends"] = friends
    merged = {**current, **patch}
    if merged.get("playerId", "").lower() in ("", addr):
        pass  # a tag is optional; the client generates a display name
    client = _client()
    if client is not None:
        client.collection(COLLECTION).document(addr).set(
            {
                "address": addr,
                "playerId": merged.get("playerId", ""),
                "savedFriends": merged.get("savedFriends", []),
                "updatedAt": _now(),
            }
        )
    _memory[addr] = {
        "playerId": merged.get("playerId", ""),
        "savedFriends": merged.get("savedFriends", []),
        "updatedAt": _now(),
    }
    return {
        "address": addr,
        "playerId": merged.get("playerId", ""),
        "savedFriends": merged.get("savedFriends", []),
        "updatedAt": _memory[addr]["updatedAt"],
    }


def _now() -> int:
    import timebase

    return int(timebase.now())


__all__ = ["COLLECTION", "MAX_FRIENDS", "ProfileError", "get", "update"]
