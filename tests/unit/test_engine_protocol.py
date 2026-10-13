"""Authoritative match-engine protocol tests (plan item 0.3).

This is the pytest migration of the engine half of `scripts/test_game_server.py`.
It is the pattern the remaining legacy suites will follow: real fixtures, one
assertion per behaviour, no shared mutable module state.

Scope here is the *existing* protocol contract — nothing about it is changed by
this migration. Behaviour that the audit found broken gets its own regression
module (`tests/adversarial/`), named after the finding.
"""

from __future__ import annotations

import hashlib

import pytest

import match_engine as engine
from match_engine import MatchError


def _intent(tag: str) -> str:
    return "0x" + hashlib.sha256(tag.encode()).hexdigest()


# --- matchmaking --------------------------------------------------------------
def test_two_players_are_paired_into_one_active_match(store, addr, opp_addr):
    first = store.enqueue(addr, 1.0)
    second = store.enqueue(opp_addr, 1.0)
    assert first.match_id == second.match_id
    assert first.status == "active"
    assert set(first.players) == {addr, opp_addr}


def test_repeated_enqueue_returns_the_same_match(store, addr):
    """Idempotent queueing: polling must not mint orphan matches."""
    first = store.enqueue(addr, 1.0)
    again = store.enqueue(addr, 1.0)
    assert again.match_id == first.match_id


def test_creator_and_joiner_roles_are_recorded(store, addr, opp_addr):
    match = store.enqueue(addr, 1.0)
    store.enqueue(opp_addr, 1.0)
    assert match.creator == addr
    assert match.joiner == opp_addr


# --- commit / reveal ----------------------------------------------------------
def test_reveal_requires_a_commit(active_match, opp_addr):
    with pytest.raises(MatchError, match="Commit before reveal"):
        engine.reveal_target(active_match, opp_addr, 0)


def test_target_delay_is_inside_the_designed_window(active_match, addr):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    target = engine.reveal_target(active_match, addr, 0)
    assert 1200 <= target["targetMs"] <= 2700


def test_reveal_issues_a_per_player_result_proof(active_match, addr, opp_addr):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    mine = engine.reveal_target(active_match, addr, 0)
    engine.commit_intent(active_match, opp_addr, 0, _intent("b"))
    theirs = engine.reveal_target(active_match, opp_addr, 0)
    assert mine["resultProof"] and theirs["resultProof"]
    assert mine["resultProof"] != theirs["resultProof"]


def test_same_intent_recommit_is_idempotent(active_match, addr):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    engine.commit_intent(active_match, addr, 0, _intent("a"))  # must not raise


def test_different_intent_within_the_window_is_rejected(active_match, addr):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    with pytest.raises(MatchError, match="already committed"):
        engine.commit_intent(active_match, addr, 0, _intent("b"))


def test_out_of_range_round_index_is_rejected(active_match, addr):
    with pytest.raises(MatchError, match="Invalid round"):
        engine.commit_intent(active_match, addr, engine.ROUNDS, _intent("a"))


def test_non_participant_cannot_act(active_match, player):
    stranger = "0x" + "99" * 20
    with pytest.raises(MatchError, match="Not a participant"):
        engine.commit_intent(active_match, stranger, 0, _intent("a"))


# --- result submission --------------------------------------------------------
def test_result_without_the_proof_is_rejected(active_match, addr, play_round):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    engine.reveal_target(active_match, addr, 0)
    with pytest.raises(MatchError, match="Invalid result proof"):
        engine.submit_result(active_match, addr, 0, 250.0, "")


def test_cross_player_proof_reuse_is_rejected(active_match, addr, opp_addr):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    mine = engine.reveal_target(active_match, addr, 0)
    engine.commit_intent(active_match, opp_addr, 0, _intent("b"))
    engine.reveal_target(active_match, opp_addr, 0)
    with pytest.raises(MatchError, match="Invalid result proof"):
        engine.submit_result(active_match, opp_addr, 0, 250.0, mine["resultProof"])


def test_subhuman_time_is_rejected_and_burns_the_round(active_match, addr, play_round):
    result = play_round(active_match, addr, 0, reaction_ms=engine.MIN_HUMAN_MS - 40)
    assert result["accepted"] is False
    assert "below human minimum" in result["reason"]
    # The round is spent — an implausible value cannot be re-rolled.
    with pytest.raises(MatchError, match="already submitted"):
        engine.submit_result(active_match, addr, 0, 250.0, "whatever")


def test_implausibly_slow_time_is_rejected(active_match, addr, play_round):
    result = play_round(active_match, addr, 0, reaction_ms=engine.MAX_HUMAN_MS + 100)
    assert result["accepted"] is False
    assert "exceeds maximum" in result["reason"]


def test_honest_reaction_is_accepted(active_match, addr, play_round):
    result = play_round(active_match, addr, 0, reaction_ms=250.0)
    assert result["accepted"] is True


def test_submitting_before_the_target_is_visible_is_rejected(active_match, addr):
    """Zero tolerance: the submission cannot predate the target's appearance."""
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    target = engine.reveal_target(active_match, addr, 0)
    result = engine.submit_result(active_match, addr, 0, 250.0, target["resultProof"])
    assert result["accepted"] is False
    assert "before the target was displayed" in result["reason"]


def test_claim_faster_than_the_server_observed_is_rejected(active_match, addr, play_round):
    """A fabricated 105ms claim while really reacting in ~600ms must fail."""
    result = play_round(active_match, addr, 0, reaction_ms=600.0)
    assert result["accepted"] is True  # honest
    # now fabricate on a fresh round
    engine.commit_intent(active_match, addr, 1, _intent("c"))
    target = engine.reveal_target(active_match, addr, 1)
    r = active_match.rounds[addr][1]
    r.revealed_at -= (r.target_ms + 600.0) / 1000.0
    fabricated = engine.submit_result(active_match, addr, 1, 105.0, target["resultProof"])
    assert fabricated["accepted"] is False
    assert "server-observed" in fabricated["reason"]


def test_expired_round_is_dead(active_match, addr, clock, play_round):
    engine.commit_intent(active_match, addr, 0, _intent("a"))
    target = engine.reveal_target(active_match, addr, 0)
    clock.advance(engine.ROUND_EXPIRY_SECONDS + 5)
    with pytest.raises(MatchError, match="expired"):
        engine.submit_result(active_match, addr, 0, 250.0, target["resultProof"])


# --- scoring / settlement -----------------------------------------------------
def test_settle_refuses_while_the_match_is_incomplete(active_match, addr, play_round):
    play_round(active_match, addr, 0, reaction_ms=250.0)
    with pytest.raises(MatchError, match="not complete"):
        engine.settle(active_match)


def test_grace_window_settles_when_the_honest_player_played_two_rounds(
    active_match, addr, opp_addr, clock, play_round
):
    """Opponent ghosts entirely; the player who played 2 rounds takes the match."""
    play_round(active_match, addr, 0, reaction_ms=220.0)
    play_round(active_match, addr, 1, reaction_ms=230.0)
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 5)
    result = engine.settle(active_match)
    assert result["status"] == "settled"
    assert result["winner"] == addr
    assert result["forfeits"][opp_addr] is True


def test_grace_window_awards_the_match_to_the_player_who_showed_up(
    active_match, addr, opp_addr, clock, play_round
):
    """Audit H24 — FIXED. This test used to pin the bug.

    It documented that a round in which NEITHER player submitted awards nobody,
    so a player who played a single round and then waited for a ghosting
    opponent ended 1-0 with no majority: the match voided and both stakes
    refunded. Abandonment cost the abandoner nothing and earned the honest
    player nothing — a free option for whoever was losing.

    The behaviour is now: an absent player forfeits the MATCH, not just the
    rounds they missed. The player who showed up and won is paid.
    """
    play_round(active_match, addr, 0, reaction_ms=220.0)
    clock.advance(engine.MATCH_SETTLE_GRACE_SECONDS + 5)
    result = engine.settle(active_match)
    assert result["status"] == "settled"
    assert result["winner"] == addr
    assert result["forfeits"][opp_addr] is True


def test_winner_is_always_a_participant(active_match, addr, opp_addr, play_round):
    for index in range(engine.ROUNDS):
        play_round(active_match, addr, index, reaction_ms=220.0 + index)
        play_round(active_match, opp_addr, index, reaction_ms=300.0 + index)
    result = engine.settle(active_match)
    assert result["status"] == "settled"
    assert result["winner"] in {addr, opp_addr}
    assert result["winner"] == addr  # the faster player wins every round


def test_forfeited_rounds_lose_the_match(active_match, addr, opp_addr, play_round):
    """A burned (invalid) round is a LOST round — anti-cheat has real teeth."""
    play_round(active_match, addr, 0, reaction_ms=engine.MIN_HUMAN_MS - 40)  # burned -> lost
    play_round(active_match, addr, 1, reaction_ms=engine.MIN_HUMAN_MS - 40)  # burned -> lost
    play_round(active_match, addr, 2, reaction_ms=250.0)  # won (250 < 302)
    for index in range(engine.ROUNDS):
        play_round(active_match, opp_addr, index, reaction_ms=300.0 + index)
    result = engine.settle(active_match)
    assert result["status"] == "settled"
    assert result["winner"] == opp_addr  # 2-1 on round wins
    assert result["forfeits"][addr] is True


def test_settled_match_is_terminal(active_match, addr, opp_addr, play_round):
    for index in range(engine.ROUNDS):
        play_round(active_match, addr, index, reaction_ms=220.0)
        play_round(active_match, opp_addr, index, reaction_ms=300.0)
    engine.settle(active_match)
    with pytest.raises(MatchError, match="not active"):
        engine.settle(active_match)


# --- disclosure rules ---------------------------------------------------------
def test_opponent_time_is_hidden_until_both_submit(active_match, addr, opp_addr, play_round):
    play_round(active_match, addr, 0, reaction_ms=250.0)
    view = active_match.public_view(for_address=addr)
    assert view["opponentTimes"] == {}
    assert view["opponentSubmitted"] == 0


def test_opponent_time_is_disclosed_after_mutual_submission(active_match, addr, opp_addr, play_round):
    play_round(active_match, addr, 0, reaction_ms=250.0)
    play_round(active_match, opp_addr, 0, reaction_ms=300.0)
    view = active_match.public_view(for_address=addr)
    assert view["opponentTimes"]["0"] == pytest.approx(300.0)
    assert view["opponentSubmitted"] == 1


def test_view_never_exposes_the_opponents_raw_round_objects(active_match, addr, opp_addr, play_round):
    play_round(active_match, addr, 0, reaction_ms=250.0)
    view = active_match.public_view(for_address=addr)
    assert "rounds" in view and isinstance(view["rounds"], int)  # count, not data
    assert "opponentRounds" not in view
