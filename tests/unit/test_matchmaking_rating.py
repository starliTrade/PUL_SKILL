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


def _play_and_settle(store, addr, opp_addr, play_round, clock, winner):
    """Pair two players, play a round, and settle so ratings update."""
    store.enqueue(addr, 1.0)
    m = store.enqueue(opp_addr, 1.0)
    # The gap is applied AFTER pairing: the band would refuse it otherwise, and
    # this test is about the ELO step, not about matchmaking.
    store.ratings[addr] = engine.DEFAULT_RATING + 400
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 400
    loser = opp_addr if winner == addr else addr
    play_round(m, winner, 0, reaction_ms=200.0, intent=b"h23")
    play_round(m, loser, 0, reaction_ms=400.0, intent=b"h23")
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 5)
    result = engine.settle(m)
    # Mirrors what api/main.py does after settling — the rating update is a
    # caller step, because `settle()` is pure match logic with no store handle.
    engine.apply_settlement_ratings(store, result)
    return result


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


def test_an_upset_moves_the_rating_more_than_an_expected_win(store):
    """The ELO property that makes the number meaningful.

    Exercised on `apply_rating_result` directly: the property belongs to the
    update rule, and driving it through a full match would only add noise.
    """
    strong = "0x" + "aa" * 20
    weak = "0x" + "bb" * 20

    # The strong player wins, as expected: a small gain.
    store.ratings[strong] = engine.DEFAULT_RATING + 400
    store.ratings[weak] = engine.DEFAULT_RATING - 400
    before = store.rating_for(strong)
    store.apply_rating_result(strong, weak)
    expected_win_gain = store.rating_for(strong) - before

    # A fresh pair, and the WEAK player wins: a large gain.
    strong2 = "0x" + "cc" * 20
    weak2 = "0x" + "dd" * 20
    store.ratings[strong2] = engine.DEFAULT_RATING + 400
    store.ratings[weak2] = engine.DEFAULT_RATING - 400
    before_weak = store.rating_for(weak2)
    store.apply_rating_result(weak2, strong2)
    upset_gain = store.rating_for(weak2) - before_weak

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
    # 600 apart: outside the initial 150 band, inside the 800 cap once widened.
    store.ratings[addr] = engine.DEFAULT_RATING + 300
    store.ratings[opp_addr] = engine.DEFAULT_RATING - 300

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
