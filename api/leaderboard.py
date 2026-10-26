"""The public podium, read through the server (audit M-04, 2026-10-22).

The client used to read the `leaderboard` collection from the browser. Three
consequences, all of them the same class as M-19:

  * the collection had to be world-readable, so every wallet address on the
    podium was enumerable by anyone;
  * every page load was billable Firestore reads, with no cache and no limit the
    server could tune;
  * the shape of the document became the API — the client had to guess field
    names (`earnedUSDT` vs `totalEarnedUSDT` was already a live bug) and a schema
    change silently emptied the podium.

This module is the server side: one query, a short TTL cache so a popular lobby
costs a handful of reads per minute instead of one per tab, and a fixed response
shape that only contains display fields.

The TTL is deliberately short (15s). A podium that lags a win by 15 seconds is
fine; a podium that lags by an hour is a support ticket.
"""

from __future__ import annotations

from typing import Any

import timebase

COLLECTION = "leaderboard"
CACHE_TTL_SECONDS = 15
MAX_ROWS = 50

_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}


def _row(doc_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """One display row, or None when the document cannot be a player row."""
    address = data.get("address") or doc_id
    if not isinstance(address, str) or not address.startswith("0x"):
        return None
    earned: float = 0.0
    for field in ("earnedUSDT", "totalEarnedUSDT"):
        value = data.get(field)
        if isinstance(value, int | float):
            earned = float(value)
            break
    best = data.get("bestReactionMs")
    wins = data.get("wins")
    matches = data.get("totalMatches")
    return {
        "address": address,
        "wins": int(wins) if isinstance(wins, int | float) else 0,
        "totalMatches": int(matches) if isinstance(matches, int | float) else 0,
        "earnedUSDT": earned,
        "bestReactionMs": int(best) if isinstance(best, int | float) else 0,
        "xp": int(data["xp"]) if isinstance(data.get("xp"), int | float) else 0,
        "level": int(data["level"]) if isinstance(data.get("level"), int | float) else 1,
    }


def top(db: Any, limit: int = 20, now: float | None = None) -> list[dict[str, Any]]:
    """The top `limit` players by wins.

    Raises on a store failure instead of returning an empty podium: "the
    leaderboard is empty" and "we could not read the leaderboard" are different
    facts, and the caller decides which to show.
    """
    limit = max(1, min(int(limit), MAX_ROWS))
    now = timebase.now() if now is None else now
    cached = _cache.get(limit)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return [dict(row) for row in cached[1]]

    # "DESCENDING" is the literal value of `firestore.Query.DESCENDING` — kept as a
    # string so this module does not import the Firestore SDK (tests pass a fake).
    query = db.collection(COLLECTION).order_by("wins", direction="DESCENDING").limit(limit)
    rows: list[dict[str, Any]] = []
    for snap in query.stream():
        row = _row(getattr(snap, "id", "") or "", dict(snap.to_dict() or {}))
        if row is not None:
            rows.append(row)
    _cache[limit] = (now, rows)
    return [dict(row) for row in rows]


def reset() -> None:
    """Test seam."""
    _cache.clear()


def age(limit: int = 20) -> float | None:
    """Seconds since the cached copy was taken (None when there is no cache)."""
    entry = _cache.get(max(1, min(int(limit), MAX_ROWS)))
    if not entry:
        return None
    return max(0.0, timebase.now() - entry[0])
