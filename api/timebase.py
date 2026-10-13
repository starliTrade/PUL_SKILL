"""The single clock seam (plan item 0.5).

Every wall-clock read in the server goes through `now()`. Tests patch
`timebase.now` to move time forward honestly instead of rewriting match state
(the legacy suites rewound `Round.revealed_at` to fake elapsed time, which
hides real timing bugs — e.g. a gate that compares against the wrong origin).

Why a module and not a function on `match_engine`: `store` and `main` both need
the same clock, and `from match_engine import now` would bind the original
function object at import time, so patching `match_engine.now` would silently
not affect them. Module-attribute access (`timebase.now()`) is always patchable.
"""

from __future__ import annotations

import time


def now() -> float:
    """Current wall-clock time as a Unix timestamp in seconds."""
    return time.time()


def now_ms() -> int:
    """Current wall-clock time in integer milliseconds (rate-limiter windows)."""
    return int(time.time() * 1000)
