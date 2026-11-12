"""Audit L-04 (found while chasing the E2E launcher) — `/api/health` must answer.

`integrity.health()` read the operator review queue with a Firestore stream and no
deadline. With the emulator down, the call never returned: measured on this
checkout, `/api/health` did not answer within 120 s — and neither
`stream(timeout=1.5)` nor `stream(retry=None)` fixed it, because the SDK blocks
while opening the channel and a per-call deadline does not reach that.

That is the worst possible place for an unbounded call. A liveness probe waits
on this endpoint; when Firestore has an incident the probe times out, the
orchestrator kills a process that was serving fine, and the replacement hangs in
exactly the same place.

So the liveness path performs NO database read. It kicks one background daemon
read (at most one outstanding) and reports the cached answer with its freshness.
These tests use a client whose stream blocks for 3 s, which is only reachable if
the read were performed inline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import integrity  # noqa: E402


def _reset_state() -> None:
    with integrity._health_lock:
        integrity._health_state.update({"open": None, "error": "", "inFlight": False, "reads": 0})


class _BlockingStream:
    """Blocks for 3 s if iterated — proves the read is not on the request path."""

    def __init__(self) -> None:
        self.seen_timeout: float | None = None

    def limit(self, _n: int):
        return self

    def where(self, *_a, **_k):
        return self

    def stream(self, timeout=None):  # noqa: ANN001
        self.seen_timeout = timeout
        time.sleep(3)
        return iter(())


class _Db:
    def __init__(self) -> None:
        self.stream = _BlockingStream()

    def collection(self, _name: str):
        return self.stream


def test_health_answers_immediately_even_when_the_read_would_hang(monkeypatch) -> None:
    _reset_state()
    db = _Db()
    monkeypatch.setattr(integrity, "_client", lambda: db)

    started = time.monotonic()
    payload = integrity.health()
    elapsed = time.monotonic() - started

    assert elapsed < 0.2, f"health took {elapsed:.2f}s — a read is on the request path"
    assert payload["readStatus"] == "pending"
    assert payload["openReviews"] is None  # not a confident 0
    assert payload["readInFlight"] is True


def test_repeated_probes_do_not_pile_up_reads(monkeypatch) -> None:
    _reset_state()
    db = _Db()
    monkeypatch.setattr(integrity, "_client", lambda: db)

    for _ in range(5):
        started = time.monotonic()
        integrity.health()
        assert time.monotonic() - started < 0.2
    assert integrity._health_state["inFlight"] is True
    # A stuck read costs ONE thread for the whole process, not one per probe.


def test_the_cached_answer_is_reported_once_the_read_finishes(monkeypatch) -> None:
    _reset_state()

    class _Ok(_BlockingStream):
        def stream(self, timeout=None):  # noqa: ANN001
            self.seen_timeout = timeout
            return iter([type("S", (), {"id": "r1", "to_dict": lambda self: {"status": "open"}})()])

    class _OkDb(_Db):
        def __init__(self) -> None:
            self.stream = _Ok()

    db = _OkDb()
    monkeypatch.setattr(integrity, "_client", lambda: db)

    # The first call kicks the read; the fake finishes fast, so "ok" may already
    # be there. Either way, no call may block.
    integrity.health()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and integrity.health()["readStatus"] == "pending":
        time.sleep(0.02)
    payload = integrity.health()
    assert payload["readStatus"] == "ok"
    assert payload["openReviews"] == 1
    assert db.stream.seen_timeout == integrity.HEALTH_READ_TIMEOUT


def test_memory_mode_needs_no_client_and_no_thread(monkeypatch) -> None:
    _reset_state()
    monkeypatch.setattr(integrity, "_client", lambda: None)
    monkeypatch.setattr(
        integrity, "_reviews", [{"status": "open"}, {"status": "resolved"}]
    )
    payload = integrity.health()
    assert payload["openReviews"] == 1
    assert payload["readStatus"] == "memory"
