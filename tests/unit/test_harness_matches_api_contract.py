"""H-20 — the harnesses must send what the API actually requires.

`/api/queue` requires `rttMs` (the ping cap is an entry gate since audit
CRITICAL-2). `scripts/chaos_suite.py` still posted `{"stake": 1}`:

    422 {"detail":[{"type":"missing","loc":["body","rttMs"]}]}

The suite treated the 422 as "the first player is not waiting" and reported

    FAIL  a staked match could be created — pairing failed

…so the scenario that exists to prove the fail-closed deposit gate never ran,
and the failure message pointed at pairing rather than at a stale contract.
Nobody noticed because that suite is not in CI and its other checks kept
passing. A harness that sends a payload the server rejects is not testing the
server.

This scans every script and test that talks to the queue and requires the two
fields the endpoint declares, so the next contract change surfaces as a
mechanical failure here instead of a mysterious "pairing failed" at 2am.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

SKIP_DIRS = {"node_modules", ".git", "out", "cache", "lib", "dist", "build", ".venv", "coverage"}


def _sources() -> list[Path]:
    out: list[Path] = []
    for base in ("scripts", "tests", "load"):
        for path in (ROOT / base).rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            out.append(path)
    return out


def test_the_queue_really_requires_rtt_ms() -> None:
    """If this ever becomes optional, the scan below can relax — not before."""
    import main as server  # noqa: PLC0415

    schemas = server.app.openapi()["components"]["schemas"]
    queue = [v for v in schemas.values() if isinstance(v, dict) and "stake" in (v.get("required") or [])]
    assert len(queue) == 1, f"expected exactly one queue-body schema, found {len(queue)}"
    assert "rttMs" in queue[0]["required"], queue[0]


def test_every_queue_call_sends_the_required_fields() -> None:
    offenders: list[str] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if "/api/queue" not in text:
            continue
        for match in re.finditer(r"/api/queue", text):
            # A window wide enough for the payload literal, narrow enough not to
            # borrow `rttMs` from the next call in the same file.
            window = text[match.start() : match.start() + 260]
            if '"stake"' not in window and "'stake'" not in window:
                continue
            # A NEGATIVE test is allowed to omit the field on purpose: it exists
            # to assert the 422. Recognise it by the assertion it makes.
            if "422" in window:
                continue
            if '"rttMs"' not in window and "'rttMs'" not in window:
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    assert not offenders, (
        "these queue calls omit rttMs, so the server answers 422 and the harness "
        f"reports it as a product failure: {offenders}"
    )
