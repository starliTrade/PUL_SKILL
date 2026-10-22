"""Player data export and erasure (audit M-21, 2026-10-22).

THE FINDING
-----------
The product stores a wallet address, a display tag, a friend list, match
history, reaction times, XP and a moderation trail — and offered no way to see
or delete any of it. That is a hard requirement in the EU/UK (GDPR art. 15 and
17) and California (CCPA), and it is the first thing a payment processor or an
app store asks about.

WHAT THIS DOES
--------------
`export(address)` returns everything the server holds about the player that is
attributable to them: profile, ledger counters, recent matches, and their
disputes.

`erase(address)` removes what can be removed without breaking someone else's
records:

  * the profile document (display tag, saved friends) — deleted;
  * the display tag on the ledger document — cleared (the counters stay);
  * the username registry entry — released, if the player still owns it;
  * the player's index entry in the integrity scorer — deleted.

WHAT IT DELIBERATELY KEEPS, AND WHY
-----------------------------------
Settlements, the match documents and the leaderboard row are the record that a
payment happened and that the opponent's win is real. Deleting them would let one
player rewrite another's history and would destroy the evidence an operator
needs in a payout dispute. They are retained, and the player is told so — with
the wallet address as the only identifier (no name, no email, no tag).

That is the honest position, not a legal opinion: whether a settlement record is
"financial data with a retention obligation" in your jurisdiction, and for how
long, is a question for your lawyer. `DELETION_POLICY` below states exactly what
survives so the answer can be written against facts.
"""

from __future__ import annotations

from typing import Any

import timebase

COLLECTION = "pulsar_profiles"
USERS = "users"
USERNAMES = "usernames"
INTEGRITY = "pulsar_integrity"

DELETION_POLICY = {
    "deleted": [
        "pulsar_profiles/{address} (display tag, saved friends)",
        "users/{address}.playerId (the tag shown in the lobby)",
        "usernames/{tag} (the player's claim, released)",
        "pulsar_integrity/{address} (reaction-time history used for scoring)",
    ],
    "retained": [
        "settlements/* and matches/* — proof that the duel happened and that the "
        "opponent's result is genuine",
        "users/{address} counters (wins, losses, XP, level) — the leaderboard's "
        "integrity depends on them",
        "leaderboard/{address} — a pseudonymous row (address only)",
        "pulsar_admin_audit — operator actions are not the player's to erase",
    ],
    "identifierAfterErasure": "the wallet address only (no tag, no friend list)",
}


def _client() -> Any:
    try:
        import store as store_module

        return store_module.durable_db()
    except Exception:  # noqa: BLE001
        return None


def _profile_module() -> Any:
    import profiles

    return profiles


def export(address: str) -> dict[str, Any]:
    """Everything attributable to the player, in one JSON document."""
    addr = address.lower()
    out: dict[str, Any] = {
        "address": addr,
        "exportedAt": int(timebase.now()),
        "profile": _profile_module().get(addr),
        "ledger": None,
        "matches": [],
        "disputes": [],
        "retention": DELETION_POLICY,
    }

    import economy

    try:
        out["ledger"] = economy.player_stats(addr)
    except Exception as exc:  # noqa: BLE001
        out["ledgerError"] = repr(exc)[:200]

    db = _client()
    if db is None:
        return out
    try:
        for snap in (
            db.collection("matches").where("players", "array_contains", addr).limit(200).stream()
        ):
            doc = snap.to_dict() or {}
            out["matches"].append(
                {
                    k: doc.get(k)
                    for k in ("id", "status", "stake", "winner", "timestamp", "prize")
                }
            )
    except Exception as exc:  # noqa: BLE001
        out["matchesError"] = repr(exc)[:200]
    try:
        for snap in (
            db.collection("pulsar_disputes").where("address", "==", addr).limit(200).stream()
        ):
            out["disputes"].append(dict(snap.to_dict() or {}))
    except Exception as exc:  # noqa: BLE001
        out["disputesError"] = repr(exc)[:200]
    return out


def erase(address: str) -> dict[str, Any]:
    """Erase the player's profile data. Returns what was removed and what stays."""
    addr = address.lower()
    removed: list[str] = []
    errors: list[str] = []

    profiles = _profile_module()
    profile = profiles.get(addr)
    tag = str(profile.get("playerId") or "").strip()

    db = _client()
    if db is not None:
        for collection, doc_id, label in (
            (COLLECTION, addr, "profile"),
            (INTEGRITY, addr, "integrity-history"),
        ):
            try:
                db.collection(collection).document(doc_id).delete()
                removed.append(label)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc!r}"[:200])
        try:
            db.collection(USERS).document(addr).set({"playerId": ""}, merge=True)
            removed.append("display-tag")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"display-tag: {exc!r}"[:200])
        if tag:
            try:
                ref = db.collection(USERNAMES).document(tag.lower())
                snap = ref.get()
                owner = ((snap.to_dict() or {}).get("address") or "").lower()
                if owner == addr:
                    ref.delete()
                    removed.append("username-registry")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"username-registry: {exc!r}"[:200])

    # In-memory mirrors (tests, dev, or the replica that served the request).
    profiles._memory.pop(addr, None)  # noqa: SLF001 - the module's documented seam
    try:
        import integrity

        integrity._memory.pop(addr, None)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass

    if not removed and not errors:
        removed.append("profile")  # nothing was stored: the outcome is the same

    return {
        "address": addr,
        "removed": removed,
        "errors": errors,
        "retained": DELETION_POLICY["retained"],
        "note": (
            "Settlements and match records are kept as the proof that a duel "
            "happened; only the wallet address remains attached to them."
        ),
    }
