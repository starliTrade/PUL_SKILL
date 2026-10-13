"""6.8 — the server's runtime dependencies must be reproducible.

`api/requirements.txt` pins the DIRECT dependencies, but their transitive
dependencies were unpinned: two installs a week apart could resolve different
`cryptography`, `cffi`, `bitarray`, ... versions, and the difference would only
show up as a settlement bug. `api/requirements.lock` (pip-compile) pins the
whole tree.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "api" / "requirements.txt"
LOCK = ROOT / "api" / "requirements.lock"


def _pins(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*([^\s;]+)", line)
        if match:
            out[match.group(1).lower()] = match.group(2)
    return out


def test_the_lock_file_exists() -> None:
    assert LOCK.is_file(), "plan item 6.8 — api/requirements.lock is missing"


def test_every_direct_runtime_dependency_is_locked() -> None:
    direct = _pins(REQUIREMENTS.read_text(encoding="utf-8"))
    locked = _pins(LOCK.read_text(encoding="utf-8"))
    assert direct, "requirements.txt pins nothing — is it the right file?"
    missing = {name: pin for name, pin in direct.items() if name not in locked}
    assert not missing, f"pinned in requirements.txt but absent from the lock: {missing}"


def test_the_lock_agrees_with_the_direct_pins() -> None:
    """A lock that contradicts requirements.txt is worse than none."""
    direct = _pins(REQUIREMENTS.read_text(encoding="utf-8"))
    locked = _pins(LOCK.read_text(encoding="utf-8"))
    conflicts = {
        name: (pin, locked[name])
        for name, pin in direct.items()
        if name in locked and locked[name] != pin
    }
    assert not conflicts, f"the lock contradicts requirements.txt: {conflicts}"


def test_the_lock_pins_the_whole_tree() -> None:
    locked = _pins(LOCK.read_text(encoding="utf-8"))
    assert len(locked) >= 20, (
        f"the lock pins only {len(locked)} packages — it does not cover the "
        "transitive tree"
    )
