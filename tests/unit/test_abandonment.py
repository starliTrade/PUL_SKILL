"""
H24 — abandoning a match must not be free.

The settle loop awards a round to the present player only when the OTHER player
submitted. A round where NEITHER submitted awards nobody:

    if va is None and vb is None:
        continue  # double forfeit: round awards nobody

So: A plays round 0 and wins (1-0). B never turns up. A waits — it cannot play
rounds 1 and 2 against nobody. Rounds 1 and 2 award nobody, A finishes 1-0, no
majority, and the match VOIDS with both stakes refunded.

A played, won, and got nothing. B did nothing and got their stake back. Under
D1 (real money) that makes abandoning a FREE OPTION: the losing player simply
leaves and recovers their stake.

The principle: the player who showed up must not be punished for the opponent's
absence. An absent player forfeits the MATCH, not just the rounds they missed.
"""
from __future__ import annotations

import match_engine as engine


def _intent(tag: str) -> str:
    return "0x" + (tag * 32)[:64]


def _submit(match, address, round_index, measured_ms, play_round):
    """One honest round for `address`."""
    play_round(match, address, round_index, measured_ms, intent=b"h24")


def _finish(match, clock):
    """Advance past the grace window so settle() is allowed."""
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 1)


# --- the finding --------------------------------------------------------------
def test_an_absent_opponent_forfeits_the_match(active_match, addr, opp_addr, play_round, clock):
    """A played and won; B never showed. A must win the match, not get a refund."""
    _submit(active_match, addr, 0, 220.0, play_round)
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["status"] == "settled", (
        "the player who showed up was refunded instead of paid (audit H24)"
    )
    assert result["winner"] == addr


def test_a_player_who_never_submitted_loses(active_match, addr, opp_addr, play_round, clock):
    """The absent side is the loser, whichever side it is."""
    _submit(active_match, opp_addr, 0, 220.0, play_round)
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["status"] == "settled"
    assert result["winner"] == opp_addr


def test_a_mutual_stall_still_voids(active_match, addr, opp_addr, clock):
    """Neither player showed up: nobody is punished, both are refunded."""
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["status"] == "void"


def test_abandoning_after_losing_a_round_does_not_refund(active_match, addr, opp_addr, play_round, clock):
    """The sharpest case: B plays round 0, loses, and walks away.

    Today B recovers their stake. That is the free option — timing out is
    strictly better than losing.
    """
    _submit(active_match, addr, 0, 220.0, play_round)  # A wins round 0
    _submit(active_match, opp_addr, 0, 400.0, play_round)  # B loses round 0
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["status"] == "settled", (
        "the player who walked away after losing was refunded (audit H24)"
    )
    assert result["winner"] == addr


def test_both_players_present_still_uses_round_wins(active_match, addr, opp_addr, play_round, clock):
    """The normal path is untouched: a genuine 1-1 tie is not a forfeit."""
    _submit(active_match, addr, 0, 220.0, play_round)
    _submit(active_match, opp_addr, 0, 400.0, play_round)
    _submit(active_match, addr, 1, 400.0, play_round)
    _submit(active_match, opp_addr, 1, 220.0, play_round)
    _finish(active_match, clock)

    result = engine.settle(active_match)

    # 1-1 with round 2 unplayed by both: no majority, and both were present —
    # so this is a genuine draw, not an abandonment.
    assert result["status"] == "void"


def test_the_forfeit_is_declared_not_fabricated(active_match, addr, opp_addr, play_round, clock):
    """The absent side must not be given an invented reaction time."""
    _submit(active_match, addr, 0, 220.0, play_round)
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["loserTimeMs"] == engine.FORFEIT_SENTINEL_MS, (
        "an absent player must be declared as a forfeit, not given a fake time"
    )


# --- the residual limitation, documented rather than hidden -------------------
def test_a_leading_player_who_abandons_still_wins(active_match, addr, opp_addr, play_round, clock):
    """KNOWN LIMIT: the server cannot tell who left.

    With equal submissions the only signal is who submitted last, which is
    noise. The rule therefore favours the LEADER, and a leading player who
    abandons still wins.

    This is recorded as a test so the behaviour is a decision rather than an
    accident. It is strictly better than the alternative: a void lets the
    TRAILING player abandon and recover a stake they were losing, which is a far
    stronger incentive than "the leader could have won anyway".

    Closing it properly needs a presence signal the server can trust (a
    heartbeat, or an on-chain forfeit), which is phase 10 work.
    """
    _submit(active_match, addr, 0, 220.0, play_round)  # A wins round 0
    _submit(active_match, opp_addr, 0, 400.0, play_round)  # B loses round 0
    _finish(active_match, clock)

    result = engine.settle(active_match)

    assert result["status"] == "settled"
    assert result["winner"] == addr
