"""Structured events for the money paths (audit M-13, 2026-10-22).

Before this module, a settlement left no machine-readable trace. `print` lines
went to stdout in whatever format the author felt like that day, with no match
id, no request id, and nothing tying a signature to the request that produced
it. When a player says "I won and never got paid", the question is answerable
only if the server can be asked: for THIS match, what did you sign, when, under
which request, and did the ledger row land?

Shape (one JSON object per line on stderr, so a log collector can parse it):

    {"component": "event", "ts": 1761..., "event": "match.settled",
     "corr": "9f1c...", "matchId": "abc", "winner": "0x..", "deadline": ..., ...}

Rules this module follows:

  * NEVER raise. A logging failure must not fail a payout.
  * No secrets and no full wallet addresses: `actor()` shortens an address to
    its first 6 and last 4 characters, because a log line is a place keys and
    PII leak from.
  * Correlation id is a contextvar set by the request middleware, so every event
    inside one request can be joined to that request's other log lines.

The admin audit trail (M-10) is a different thing with different guarantees: it
is a durable, queryable collection. This is the operational stream.
"""

from __future__ import annotations

import contextvars
import json
import os
import secrets
import sys
from typing import Any

import timebase

_COMPONENT = "event"

# Request-scoped correlation id. Contextvars (not a module global) because the
# server handles requests concurrently in one event loop/thread pool.
_CORR: contextvars.ContextVar[str] = contextvars.ContextVar("pulsar_correlation", default="-")

_SEEN: dict[str, int] = {}


def new_correlation() -> str:
    """A short, URL-safe id for one request."""
    return secrets.token_hex(8)


def set_correlation(value: str) -> contextvars.Token[str]:
    return _CORR.set(value)


def reset_correlation(token: contextvars.Token[str]) -> None:
    _CORR.reset(token)


def correlation() -> str:
    return _CORR.get()


def _redact(value: Any) -> Any:
    """Shorten anything that looks like a wallet address or a key."""
    if not isinstance(value, str):
        return value
    if len(value) >= 40 and value[:2].lower() == "0x":
        return f"{value[:6]}…{value[-4:]}"
    if value.lower().startswith("bearer "):
        return "bearer ***"
    return value


def emit(event: str, **fields: Any) -> None:
    """Write one structured line. Never raises, never blocks on I/O errors."""
    if not enabled():
        return
    try:
        payload: dict[str, Any] = {
            "component": _COMPONENT,
            "ts": int(timebase.now()),
            "event": event,
            "corr": correlation(),
        }
        for key, value in fields.items():
            payload[key] = _redact(value)
        line = json.dumps(payload, separators=(",", ":"), default=str)
        _SEEN[event] = int(_SEEN.get(event, 0)) + 1
        print(line, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - logging must never break a payout
        pass


def counts() -> dict[str, int]:
    """Event counters since boot, exposed on /api/health (cheap diagnostics)."""
    return dict(_SEEN)


def enabled() -> bool:
    """Events can be silenced in tests that assert on stderr."""
    return os.environ.get("PULSAR_EVENT_LOG", "1") != "0"


def reset() -> None:
    """Test seam."""
    _SEEN.clear()
    _CORR.set("-")
