"""
H23 / G5 — matchmaking must consider skill.

`MatchStore.enqueue` pairs the FIRST two players in a stake bucket, in arrival
order. Nothing about their ability is considered.

For a free game that is merely a bad experience. Under D1 (real money) it is a
money-transfer mechanism: a novice and a veteran queue at the same stake, are
paired instantly, and the novice's stake moves to the veteran. The game takes
money from beginners by design, and no amount of anti-cheat fixes that — the
veteran is not cheating.

The fix is a rating and a pairing band:

  - an ELO-style rating per player, updated from settled match outcomes;
  - pairing prefers an opponent within a band, and the band WIDENS with wait
    time so nobody waits forever (a queue that never matches is its own
    failure).

The rating is derived from outcomes rather than from raw reaction times: a
reaction time is one noisy sample, and a rating built on noise would move every
player's number by tens of points per match.
"""
from __future__ import annotations

import pytest

import match_engine as engine
from match_engine import MatchError


def _play_and_settle(store, addr, opp_addr, play_round, clock, winner):
    """Pair two players, play a round, and settle so ratings update."""
    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 1.0)
    loser = opp_addr if winner == addr else addr
    play_round(m, winner, 0, reaction_ms=200.0, intent=b"h23")
    play_round(m, loser, 0, reaction_ms=400.0, intent=b"h23")
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 5)
    return engine.settle(m)


# --- the rating ---------------------------------------------------------------
def test_a_new_player_starts_at_the_default_rating(store, addr):
    assert store.rating_for(addr) == engine.DEFAULT_RATING


def test_winning_raises_the_rating_and_losing_lowers_it(store, addr, opp_addr, play_round, clock):
    before_a = store.rating_for(addr)
    before_b = store.rating_for(opp_addr)

    _play_and_settle(store, addr, opp_addr, play_round, clock, winner=addr)

    assert store.rating_for(addr) > before_a
    assert store.rating_for(opp_addr) < before_b


def test_the_rating_change_is_zero_sum(store, addr, opp_addr, play_round, clock):
    """Ratings must not inflate: what one player gains, the other loses."""
    before_a = store.rating_for(addr)
    before_b = store.rating_for(opp_addr)

    _play_and_settle(store, addr, opp_addr, play_round, clock, winner=addr)

    gained = store.rating_for(addr) - before_a
    lost = before_b - store.rating_for(opp_addr)
    assert gained == pytest.approx(lost, abs=0.01)


def test_an_upset_moves_the_rating_more_than_an_expected_win(store, addr, opp_addr, play_round, clock):
    """The ELO property that makes the number meaningful."""
    # A is much stronger than B.
    store.ratings[addr] = engine.DEFAULT_RATING + 400
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 400

    before_strong = store.rating_for(addr)
    _play_and_settle(store, addr, opp_addr, play_round, clock, winner=addr)
    expected_win_gain = store.rating_for(addr) - before_strong

    # Reset and make the WEAK player win instead.
    store.ratings[addr] = engine.DEFAULT_RATING + 400
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 400
    before_weak = store.rating_for(opp_addr)
    _play_and_settle(store, addr, opp_addr, play_round, clock, winner=opp_addr)
    upset_gain = store.rating_for(opp_addr) - before_weak

    assert upset_gain > expected_win_gain


# --- the pairing band ---------------------------------------------------------
def test_mismatched_players_are_not_paired_immediately(store, addr, opp_addr):
    store.ratings[addr] = engine.DEFAULT_RATING + 600
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 600

    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 1.0)

    assert m.status == "waiting", (
        "a 1200-point mismatch was paired instantly — the weaker player's stake "
        "is a gift (audit H23)"
    )


def test_similar_players_are_paired(store, addr, opp_addr):
    store.ratings[addr] = engine.DEFAULT_RATING + 20
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 20

    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 1.0)

    assert m.status == "active"


def test_the_band_widens_with_wait_time(store, addr, opp_addr, clock):
    """A queue that never matches is its own failure."""
    store.ratings[addr] = engine.DEFAULT_RATING + 600
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 600

    store.enqueue(addr, 1.0)
    clock.advance(engine.RATING_BAND_WIDEN_SECONDS * 20)
    m = store.enqueue(opp_addr, 1.0)

    assert m.status == "active", "the band never widened — the players wait forever"


def test_a_different_stake_is_still_a_different_bucket(store, addr, opp_addr):
    """Skill pairing must not break the stake gate."""
    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 5.0)

    assert m.status == "waiting"
    assert m.stake == 5.0
