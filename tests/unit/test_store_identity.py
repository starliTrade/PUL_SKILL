"""`DurableMatchStore.identity` — the gate's cheap read.

Audit 2026-10-14 (plan item 10.3): the deposit gate ran a full `get()` before
every round action and `update()` read the match again, so each commit / reveal
/ submit cost two Firestore reads — 37 of a match's 47. `identity` serves the
gate from the in-process mirror, which is safe because the gate's inputs
(`stake`, `players`) are immutable after activation and the ON-CHAIN state it
verifies is still read fresh every call.

These tests exist because that is a SECURITY path: a cache in front of a gate
must be provably a cache, never a different answer.
"""
from __future__ import annotations

from api.store import DurableMatchStore, Match


def _durable() -> DurableMatchStore:
    """A durable store with a fake Firestore, so no emulator is needed."""
    s = DurableMatchStore(backend="memory")
    s.backend_name = "firestore"
    s._fs_store = object()  # truthy: take the durable branch
    return s


def _match(match_id: str = "a" * 32, status: str = "active") -> Match:
    return Match(
        match_id=match_id,
        stake=1.0,
        created_at=0.0,
        players={"0xaa": {"address": "0xaa"}, "0xbb": {"address": "0xbb"}},
        creator="0xaa",
        status=status,
    )


def test_identity_serves_a_live_match_from_the_mirror(monkeypatch) -> None:
    s = _durable()
    m = _match()
    s.memory.put(m)

    def _explode(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("identity must not hit Firestore for a mirrored match")

    monkeypatch.setattr(s, "get", _explode)
    assert s.identity(m.match_id) is not None
    assert s.identity(m.match_id).players == m.players


def test_identity_falls_back_when_the_mirror_is_empty(monkeypatch) -> None:
    """A cache miss must be a real read, never an empty answer."""
    s = _durable()
    called: list[str] = []

    def _get(match_id: str) -> Match:
        called.append(match_id)
        return _match(match_id)

    monkeypatch.setattr(s, "get", _get)
    out = s.identity("b" * 32)
    assert called == ["b" * 32], "an unknown match must be read from the store"
    assert out.match_id == "b" * 32


def test_identity_does_not_serve_a_terminal_match(monkeypatch) -> None:
    """A settled or void match must not be cached as live.

    Serving a terminal match from the mirror would let a gate decision be made
    against a duel that is over.
    """
    s = _durable()
    s.memory.put(_match(status="settled"))
    called: list[str] = []

    def _get(match_id: str) -> Match:
        called.append(match_id)
        return _match(match_id, status="settled")

    monkeypatch.setattr(s, "get", _get)
    s.identity("a" * 32)
    assert called == ["a" * 32], "a terminal match must be re-read, not served from the mirror"


def test_identity_on_the_memory_backend_is_just_get(monkeypatch) -> None:
    s = DurableMatchStore(backend="memory")
    m = _match()
    s.memory.put(m)
    assert s.identity(m.match_id).match_id == m.match_id


def test_store_contention_is_recognised_as_retryable() -> None:
    """A busy store must be a retryable 503, not a 500.

    Found by the 1000-poller load run: `ValueError: Failed to commit transaction
    in 5 attempts` escaped as an HTTP 500, and 157 of 157 queue requests failed
    that way. A 500 says "do not retry"; the truth is "the store was busy".
    """
    from api.main import _is_store_contention

    assert _is_store_contention(ValueError("Failed to commit transaction in 5 attempts."))
    assert _is_store_contention(RuntimeError("ABORTED: too much contention"))
    # A real validation failure must NOT be dressed up as retryable.
    assert not _is_store_contention(ValueError("Invalid stake"))
    assert not _is_store_contention(KeyError("matchId"))
