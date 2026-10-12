"""
H1 — the winner must be decided by reaction time, not by network distance.

`_rank_time` returns `observed_ms`, the reaction the SERVER witnessed
(`elapsed − target_ms`). But `elapsed` runs from when the server SENT the target
to when the submission ARRIVED, so:

    observed = true reaction + network latency + submit latency

Network latency can only INFLATE it. A player 10ms from the server and a player
100ms away who react identically get observed times 45ms apart — and in a game
whose whole range is ~150-400ms, that decides the match. With real money
(D1 = option D) that means funds move from the faster player to the one nearer
the server.

Decision (recorded in the plan): option (b) + a ping cap.

    compensated = observed − min_rtt/2

The MINIMUM reported RTT is what makes this safe. A naive `observed − rtt/2` is
itself an exploit: a larger `rtt` yields a smaller `compensated`, i.e. looking
faster. The minimum cannot be inflated (the true value stays in the set) and
cannot be deflated below the network floor — and deflating only REDUCES the
compensation, so there is no incentive either way.
"""
from __future__ import annotations

import pytest

import match_engine as engine
from match_engine import MatchError, commit_intent, reveal_target, submit_result


def _intent(tag: str) -> str:
    return "0x" + (tag * 32)[:64]


def _play(match, address, round_index, measured_ms, rtt_ms):
    """Commit → reveal → submit one round, reporting an RTT."""
    commit_intent(match, address, round_index, _intent(str(round_index)))
    reveal_target(match, address, round_index)
    proof = match.rounds[address][round_index].result_proof
    submit_result(match, address, round_index, measured_ms, proof, rtt_ms=rtt_ms)


# --- the finding -------------------------------------------------------------
def test_equal_reaction_different_latency_is_a_tie(active_match, addr, opp_addr):
    """Two players who reacted identically must tie, whatever their latency.

    `addr` is 10ms from the server, `opp_addr` is 100ms away. Both react in
    220ms. Today the near player's observed time is ~225ms and the far player's
    ~270ms, so the near player wins a round they did not earn.
    """
    near_rtt, far_rtt = 10.0, 100.0
    reaction = 220.0

    # The server witnesses the reaction plus half the round trip (one way).
    _play(active_match, addr, 0, reaction, near_rtt)
    _play(active_match, opp_addr, 0, reaction, far_rtt)

    # Simulate what the server actually observed.
    active_match.rounds[addr][0].observed_ms = reaction + near_rtt / 2
    active_match.rounds[opp_addr][0].observed_ms = reaction + far_rtt / 2

    va = engine._rank_time(active_match.rounds[addr][0], active_match.rounds[addr][0].min_rtt_ms)
    vb = engine._rank_time(active_match.rounds[opp_addr][0], active_match.rounds[opp_addr][0].min_rtt_ms)

    assert va == pytest.approx(reaction, abs=1.0)
    assert vb == pytest.approx(reaction, abs=1.0)
    assert va == pytest.approx(vb, abs=1.0), (
        "equal reactions must tie regardless of network distance (audit H1)"
    )


def test_the_near_player_no_longer_wins_by_default(active_match, addr, opp_addr):
    """The concrete money case: identical reactions, different distance."""
    reaction = 220.0
    _play(active_match, addr, 0, reaction, 10.0)
    _play(active_match, opp_addr, 0, reaction, 100.0)

    active_match.rounds[addr][0].observed_ms = reaction + 5.0
    active_match.rounds[opp_addr][0].observed_ms = reaction + 50.0

    winner = engine._round_winner(
        active_match.rounds[addr], active_match.rounds[opp_addr], 0
    )
    assert winner in ("tie", "draw"), (
        f"the nearer player won a round neither player was faster in (got {winner!r})"
    )


# --- the compensation cannot be gamed ----------------------------------------
def test_inflating_the_reported_rtt_does_not_help(active_match, addr):
    """A cheater who reports a huge RTT must not gain compensation."""
    _play(active_match, addr, 0, 220.0, 10.0)
    _play(active_match, addr, 1, 220.0, 5000.0)  # absurd inflation

    r = active_match.rounds[addr][0]
    assert r.min_rtt_ms == pytest.approx(10.0), (
        "the minimum RTT must ignore an inflated report (audit H1)"
    )


def test_the_minimum_is_kept_across_rounds(active_match, addr):
    _play(active_match, addr, 0, 220.0, 120.0)
    _play(active_match, addr, 1, 220.0, 40.0)
    _play(active_match, addr, 2, 220.0, 90.0)

    # The minimum is per match, not per round.
    assert active_match.min_rtt_ms[addr] == pytest.approx(40.0)


def test_a_negative_rtt_is_rejected(active_match, addr):
    """A negative report would ADD time; it must not be accepted."""
    commit_intent(active_match, addr, 0, _intent("0"))
    reveal_target(active_match, addr, 0)
    proof = active_match.rounds[addr][0].result_proof

    with pytest.raises(MatchError, match="rtt"):
        submit_result(active_match, addr, 0, 220.0, proof, rtt_ms=-50.0)


def test_compensation_is_capped(active_match, addr):
    """A huge RTT must not compensate beyond the cap."""
    _play(active_match, addr, 0, 220.0, 10_000.0)

    r = active_match.rounds[addr][0]
    r.observed_ms = 220.0 + 5000.0
    ranked = engine._rank_time(r, r.min_rtt_ms)
    assert ranked >= 220.0, "compensation must never make a player look faster than they were"


# --- the ping cap ------------------------------------------------------------
def test_a_player_above_the_ping_cap_is_refused_at_queue_time(store, addr, clock):
    """The cap is an entry gate with a clear message, not a silent loss."""
    with pytest.raises(MatchError, match="ping"):
        store.enqueue(addr, 1.0, rtt_ms=engine.MAX_QUEUE_RTT_MS + 1)


def test_a_player_within_the_cap_is_accepted(store, addr):
    store.enqueue(addr, 1.0, rtt_ms=engine.MAX_QUEUE_RTT_MS - 1)
