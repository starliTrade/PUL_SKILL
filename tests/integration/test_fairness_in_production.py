"""CRITICAL-2 + HIGH-6 — the fairness controls must exist in PRODUCTION.

The ping cap, the rating band and the latency compensation lived in
`match_engine.MatchStore`, which production NEVER instantiates: `main.store` is a
`DurableMatchStore` -> `InMemoryStore`/`FirestoreStore`. The tests that
"guarded" them used the dead class, so reverting the production behaviour
changed nothing — the project's own rule ("a gate that only exists in tests is
not a gate") broken by the very fixes that wrote it down.

These tests drive `main.store`, the object the server actually uses.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)
os.environ.setdefault("PULSAR_ENV", "dev")

import main as server  # noqa: E402

import match_engine as engine  # noqa: E402
from match_engine import MatchError  # noqa: E402

A = "0x" + "aa" * 20
B = "0x" + "bb" * 20
C = "0x" + "cc" * 20


@pytest.fixture(autouse=True)
def memory_backend(monkeypatch):
    """The production store, on its memory backend, with a clean queue."""
    monkeypatch.setattr(server.store, "_fs_store", None)
    mem = server.store.memory
    mem.matches.clear()
    mem.queue.clear()
    mem.player_match.clear()
    mem.ratings.clear()
    return server.store


# --- the ping cap (audit H1) --------------------------------------------------


def test_the_production_store_refuses_a_player_above_the_ping_cap():
    with pytest.raises(MatchError) as exc:
        server.store.enqueue(A, 1.0, engine.MAX_QUEUE_RTT_MS + 5000)
    assert "Ping too high" in str(exc.value), (
        "the ping cap does not exist on the store production runs (audit CRITICAL-2)"
    )


def test_the_production_store_accepts_a_player_within_the_cap():
    m = server.store.enqueue(A, 1.0, 25.0)
    assert m.status == "waiting"


def test_the_durable_backend_enforces_the_ping_cap_too():
    """The cap must not be a memory-backend-only feature."""
    import inspect

    src = inspect.getsource(type(server.store._fs_store).enqueue) if server.store._fs_store else ""
    if not src:
        # No Firestore configured here; assert the shared gate is called on the
        # durable path by reading the source instead of skipping silently.
        import store as store_module

        fs_src = inspect.getsource(store_module.FirestoreStore.enqueue)
        assert "check_ping_cap" in fs_src, (
            "the durable enqueue does not apply the ping cap (audit CRITICAL-2)"
        )
    else:
        assert "check_ping_cap" in src


# --- the rating band (audit H23) ----------------------------------------------


def test_the_production_store_pairs_within_a_rating_band():
    server.store.memory.ratings[A] = 1200.0
    server.store.memory.ratings[B] = 1200.0 + engine.MAX_RATING_BAND + 500
    server.store.enqueue(A, 1.0, 20.0)
    m = server.store.enqueue(B, 1.0, 20.0)
    assert m.status == "waiting", (
        "a 1300-point rating gap was paired instantly — the band does not exist "
        "on the store production runs (audit CRITICAL-2)"
    )


def test_the_production_store_pairs_similar_ratings():
    server.store.memory.ratings[A] = 1200.0
    server.store.memory.ratings[B] = 1250.0
    first = server.store.enqueue(A, 1.0, 20.0)
    second = server.store.enqueue(B, 1.0, 20.0)
    assert second.match_id == first.match_id
    assert second.status == "active"


# --- the RTT record (audit CRITICAL-2) ----------------------------------------


def test_the_reported_rtt_is_recorded_on_the_match():
    m = server.store.enqueue(A, 1.0, 33.0)
    assert m.min_rtt_ms.get(A) == 33.0


def test_the_rtt_record_survives_a_durable_round_trip():
    """It was never persisted, so every re-read on the durable backend lost it."""
    import store as store_module

    m = server.store.enqueue(A, 1.0, 33.0)
    doc = store_module._match_to_doc(m)
    assert "min_rtt_ms" in doc, (
        "min_rtt_ms is not persisted — the durable backend loses it on every read "
        "(audit CRITICAL-2)"
    )
    assert store_module._match_from_doc(doc).min_rtt_ms.get(A) == 33.0


# --- the RTT exploit (audit HIGH-6) -------------------------------------------


def test_a_reported_rtt_cannot_change_the_ranking(active_match, addr, opp_addr, play_round):
    """The compensation is gone: the ranking is the server-observed reaction."""
    play_round(active_match, addr, 0, 250.0)
    play_round(active_match, opp_addr, 0, 250.0)

    ra = active_match.rounds[addr][0]
    rb = active_match.rounds[opp_addr][0]
    va = engine._rank_time(ra, 1000.0)
    vb = engine._rank_time(rb, 20.0)
    # The two rewinds differ by float noise, not by 490ms: with the compensation
    # gone the reported RTT cannot move the ranking at all.
    assert abs(va - vb) < 1.0, (
        f"a client-reported RTT still moves the ranking by {abs(va - vb):.1f}ms — "
        "that is a stake-transfer exploit (audit HIGH-6)"
    )


def test_inflating_the_reported_rtt_does_not_win_the_match(store, addr, opp_addr, play_round):
    """End to end: the RTT-inflator reacts identically and must not win."""
    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 1.0)
    # The attacker claims a 1000ms round trip on every round.
    for idx in range(3):
        play_round(m, addr, idx, 250.0)
        play_round(m, opp_addr, idx, 250.0)
    m.min_rtt_ms[addr] = 1000.0
    m.min_rtt_ms[opp_addr] = 20.0

    result = engine.settle(m)
    # Identical reactions: the match cannot be decided in the inflator's favour
    # by the RTT alone.
    assert result.get("winner", "") != addr, (
        "reporting a large RTT won the match (audit HIGH-6)"
    )


# --- pairing by closest connection (audit H1) ---------------------------------


def test_pairing_prefers_the_closest_connection(clock):
    """With two compatible opponents, the nearer connection is chosen.

    Two open waiting matches can only coexist while their rating bands do not
    overlap; the clock is advanced so both bands widen enough to admit C.
    """
    server.store.memory.ratings[A] = 1200.0
    server.store.memory.ratings[B] = 2200.0
    server.store.enqueue(A, 1.0, 20.0)   # far
    server.store.enqueue(B, 1.0, 300.0)  # near
    clock.advance(60)                    # widen both bands
    server.store.memory.ratings[C] = 1700.0

    m = server.store.enqueue(C, 1.0, 290.0)
    assert m.status == "active"
    assert C in m.players and B in m.players, (
        "the far connection was chosen over the near one (audit H1)"
    )


def test_a_reservation_outranks_the_closest_connection():
    """Someone asked for THIS player by name; a nearer stranger must not win."""
    a_match = server.store.enqueue(A, 1.0, 20.0, C)  # far, but reserved for C
    assert a_match.status == "waiting"
    server.store.enqueue(B, 1.0, 300.0)              # near, open

    m = server.store.enqueue(C, 1.0, 290.0)
    assert m.match_id == a_match.match_id, (
        "a reservation was lost to the closest-connection tiebreak (audit M27)"
    )
