"""Admin action log (audit M-10, 2026-10-22).

THE FINDING
-----------
Every operator action was gated by one shared secret in a header, and the only
trace of what was done with it was `print(..., file=sys.stderr)` on two
endpoints. So:

  * there was no record of who voided a duel, when, or why (a write to stderr is
    not a record — it is not queryable, it is lost on restart, and it is gone as
    soon as the log rotates);
  * a leaked admin secret could void matches and ban players with nothing that
    could later be reconstructed;
  * /api/admin/ban, /unban, /review and the deposit-limit endpoint left NO trace
    at all.

WHAT THIS IS
------------
One append-only collection (`pulsar_admin_audit`) plus a structured stderr line
for every administrative decision. Each entry carries the action, the target,
the operator-supplied reason, the source IP, and a correlation id. Reads are
exposed at `GET /api/admin/audit` so the trail is usable, not decorative.

WHAT IT IS NOT
--------------
- It does not authenticate the operator beyond the shared secret (2FA/mTLS is a
  product decision, tracked in the audit as M-10's remaining half).
- It is not tamper-proof against someone with database access. A real chain of
  custody needs append-only storage with a separate trust boundary; what this
  buys is that ordinary operation, mistakes and abuse leave evidence.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

import timebase

COLLECTION = "pulsar_admin_audit"
MAX_READ = 200

_memory: list[dict[str, Any]] = []
_state: dict[str, Any] = {"written": 0, "failures": 0, "lastError": ""}


def _client() -> Any:
    try:
        import store as store_module

        return store_module.durable_db()
    except Exception:  # noqa: BLE001 - no store configured is a normal state
        return None


def record(
    action: str,
    *,
    target: str = "",
    detail: Any = "",
    actor: str = "admin-secret",
    source_ip: str = "",
) -> dict[str, Any]:
    """Append one administrative decision. Never raises into the request."""
    entry = {
        "id": uuid.uuid4().hex,
        "at": int(timebase.now()),
        "action": str(action)[:80],
        "target": str(target)[:120],
        "detail": (str(detail)[:500] if detail is not None else ""),
        "actor": str(actor)[:120],
        "sourceIp": str(source_ip)[:64],
    }
    _memory.append(entry)
    # Structured, greppable, and one line per decision — the thing a postmortem
    # actually reads. JSON, so a log pipeline can index it.
    print(
        json.dumps({"component": "admin_audit", **entry}, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )

    db = _client()
    if db is not None:
        try:
            db.collection(COLLECTION).document(entry["id"]).set(entry)
            _state["written"] = int(_state["written"]) + 1
        except Exception as exc:  # noqa: BLE001
            _state["failures"] = int(_state["failures"]) + 1
            _state["lastError"] = repr(exc)[:200]
            print(f"[admin_audit] durable write failed: {exc!r}", file=sys.stderr)
    return entry


def recent(limit: int = 50) -> list[dict[str, Any]]:
    """Newest first. Durable when available, process memory otherwise."""
    limit = max(1, min(int(limit), MAX_READ))
    db = _client()
    if db is not None:
        try:
            rows = [
                dict(snap.to_dict() or {"id": snap.id})
                for snap in db.collection(COLLECTION)
                .order_by("at", direction=_DESC)
                .limit(limit)
                .stream()
            ]
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001
            print(f"[admin_audit] durable read failed: {exc!r}", file=sys.stderr)
    return list(reversed(_memory[-limit:]))


def health() -> dict[str, Any]:
    return {
        "entries": len(_memory),
        "written": _state["written"],
        "failures": _state["failures"],
        "lastError": _state["lastError"],
    }


class _Desc:
    """Firestore's `Query.DESCENDING`, without importing the SDK for it."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "DESCENDING"


_DESC = _Desc()
