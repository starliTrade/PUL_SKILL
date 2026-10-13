"""
H1 — the winner must be decided by reaction time, not by network distance.

(Revised 2026-10-13 by audit HIGH-6: the latency compensation was removed. See
below for what replaced it and why the old safety argument was false.)

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

    compensated = observed − min_rtt/2      <-- REMOVED, see below

Audit HIGH-6 (2026-10-13): the compensation was itself the exploit. `min_rtt`
came ONLY from the client's reported `rttMs` — the server never measures the
network's share of a round — so the claim that "the minimum cannot be inflated
because the true value stays in the set" was false: there was no
server-measured value in the set. Reporting a large RTT on every round bought up
to MAX_COMPENSATION_MS (150ms), decisive in a 150–400ms game, i.e. a
stake-transfer exploit under real money.

The ranking is now the server-observed reaction, and fairness is enforced where
the server can act without being gameable:

  * the ping cap at queue time (`store.check_ping_cap`) — lying about a HIGH
    ping only excludes you; lying about a LOW one buys nothing;
  * pairing by closest connection (`store.choose_opponent`) — both players'
    network conditions are comparable before their reactions are compared.

Both live in `api/store.py`, which is what production runs. They used to live in
`match_engine.MatchStore`, a class production never instantiates (audit
CRITICAL-2), so neither applied to a real duel.
"""
from __future__ import annotations

import pytest

import match_engine as engine
from match_engine import MatchError, commit_intent, reveal_target, submit_result


def _intent(tag: str) -> str:
    return "0x" + (tag * 32)[:64]


def _play(match, address, round_index, measured_ms, rtt_ms):
    """Commit → reveal → submit one round, reporting an RTT.

    `observed_ms` is then set to what the server WOULD have witnessed: the true
    reaction plus the one-way network latency. That is the whole point of H1 —
    the server cannot see the reaction, only the reaction plus the distance.
    """
    commit_intent(match, address, round_index, _intent(str(round_index)))
    reveal_target(match, address, round_index)
    r = match.rounds[address][round_index]
    # Rewind so the server observes exactly `measured_ms`, like `play_round`.
    if r.revealed_at:
        r.revealed_at -= (r.target_ms + measured_ms) / 1000.0
    submit_result(match, address, round_index, measured_ms, r.result_proof, rtt_ms=rtt_ms)
    r.observed_ms = measured_ms + rtt_ms / 2.0


# --- the finding -------------------------------------------------------------
def test_the_ranking_is_the_server_observed_reaction(active_match, addr, opp_addr):
    """The ranking is what the server witnessed — no client number is subtracted.

    This replaces the old "equal reactions tie regardless of latency" assertion.
    That property was bought with a client-reported RTT, which is the exploit
    (audit HIGH-6). The server cannot separate the network's share of a round
    from the reaction, so it must not pretend to: it ranks on what it observed
    and keeps the network comparable by the ping cap and by pairing.
    """
    _play(active_match, addr, 0, 220.0, 10.0)
    _play(active_match, opp_addr, 0, 220.0, 100.0)

    ra = active_match.rounds[addr][0]
    rb = active_match.rounds[opp_addr][0]
    va = engine._rank_time(ra, active_match.min_rtt_ms[addr])
    vb = engine._rank_time(rb, active_match.min_rtt_ms[opp_addr])

    assert va == pytest.approx(ra.observed_ms, abs=0.01)
    assert vb == pytest.approx(rb.observed_ms, abs=0.01)
    # ...and no reported RTT can move either one.
    assert engine._rank_time(ra, 10_000.0) == va
    assert engine._rank_time(rb, 0.0) == vb


def test_a_huge_reported_rtt_cannot_buy_speed(active_match, addr):
    """The concrete money case: report a wild round trip, gain nothing."""
    _play(active_match, addr, 0, 220.0, 10_000.0)
    r = active_match.rounds[addr][0]
    r.observed_ms = 220.0
    assert engine._rank_time(r, active_match.min_rtt_ms[addr]) == 220.0, (
        "a client-reported RTT still buys speed — a stake-transfer exploit "
        "(audit HIGH-6)"
    )


# --- the compensation cannot be gamed ----------------------------------------
def test_inflating_the_reported_rtt_does_not_help(active_match, addr):
    """A cheater who reports a huge RTT must not gain compensation."""
    _play(active_match, addr, 0, 220.0, 10.0)
    _play(active_match, addr, 1, 220.0, 5000.0)  # absurd inflation

    assert active_match.min_rtt_ms[addr] == pytest.approx(10.0), (
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


def test_no_reported_rtt_can_make_a_player_look_faster(active_match, addr):
    """There is no compensation left to cap — the ranking is the observation."""
    _play(active_match, addr, 0, 220.0, 10_000.0)

    r = active_match.rounds[addr][0]
    r.observed_ms = 220.0
    assert engine._rank_time(r, active_match.min_rtt_ms[addr]) == 220.0
    assert engine._rank_time(r, 0.0) == 220.0


# --- the ping cap ------------------------------------------------------------
def test_a_player_above_the_ping_cap_is_refused_at_queue_time(store, addr, clock):
    """The cap is an entry gate with a clear message, not a silent loss."""
    with pytest.raises(MatchError, match="[Pp]ing"):
        store.enqueue(addr, 1.0, rtt_ms=engine.MAX_QUEUE_RTT_MS + 1)


def test_a_player_within_the_cap_is_accepted(store, addr):
    store.enqueue(addr, 1.0, rtt_ms=engine.MAX_QUEUE_RTT_MS - 1)
