"""Audit L-06 — a latency without its conditions is not a measurement.

`docs/LOAD-REPORT.md` presented a 50-user emulator run and a 1000-user run as if
they answered the same question, with no machine, no process count, and no
statement of what a reader may NOT conclude. The number that hurt was "the
application is not the bottleneck": the run behind it used 50 users and a
single-process emulator, and the 1000-user run was on a box where the load
generator shared the CPU.

This does not re-run the load test (that is `load/locustfile.py`, and it needs a
machine). It pins the properties that make the document readable and keep the
next edit from dropping them.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "LOAD-REPORT.md").read_text(encoding="utf-8")


def _paragraphs() -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", DOC) if p.strip()]


def test_it_says_what_it_does_NOT_establish() -> None:
    assert "It does not say" in DOC
    assert "unknown" in DOC.lower()
    assert "capacity" in DOC.lower()


def test_it_names_the_machine_and_the_process_count() -> None:
    """CPU count is the first thing that makes a latency comparable."""
    assert re.search(r"\b2 vCPU\b", DOC)
    assert "one\n  worker process" in DOC or "worker process" in DOC


def test_it_names_the_generator_and_that_it_shares_the_cpu() -> None:
    assert "locust" in DOC.lower()
    assert "same two cores" in DOC or "shares the same two vCPUs" in DOC


def test_the_1000_user_numbers_are_not_presented_as_application_cost() -> None:
    """The artifact, stated: a no-op endpoint reporting seconds.

    If someone deletes that explanation, the table above it silently becomes a
    claim about the API.
    """
    assert "touches nothing" in DOC
    assert "saturated host" in DOC


def test_the_historical_emulator_numbers_are_marked_unreproducible() -> None:
    """They were measured on 2026-10-13 with java + the Firebase CLI, neither of
    which exists in the environment that rewrote this file. Keeping them without
    that label invites someone to cite them as current."""
    assert "2026-10-13" in DOC
    assert "cannot be re-measured here" in DOC


def test_no_bare_concurrency_claim_without_its_store() -> None:
    """Every paragraph that names a concurrency figure must also name a store.

    This is the specific failure the finding described: "1000 concurrent" sitting
    next to numbers produced with the emulator, with nothing saying so.
    """
    for para in _paragraphs():
        if re.search(r"\b1[0-9]{2,3}\b\s*(?:concurrent|users|virtual users)", para):
            low = para.lower()
            assert any(
                word in low for word in ("memory", "emulator", "firestore", "store")
            ), f"concurrency claim with no store: {para[:120]!r}"


def test_the_measurement_recipe_is_still_here() -> None:
    """A report that cannot be reproduced is an anecdote."""
    for step in ("scripts/load_sessions.py", "-u 1000", "/api/metrics", "Firestore"):
        assert step in DOC, step
