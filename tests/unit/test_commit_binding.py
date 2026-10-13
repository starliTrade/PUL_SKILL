"""
H2 — the round commitment must be real.

`commit_intent` allowed a commit to be REPLACED once `COMMIT_WINDOW_SECONDS`
had elapsed:

    if r.commit_hash and now - r.commit_at < COMMIT_WINDOW_SECONDS:
        if r.commit_hash != intent_hash.lower():
            raise MatchError("Round already committed")
        return
    r.commit_hash = intent_hash.lower()   # ← a second commit overwrites it

So a player could commit, reveal the target, wait out the window, and commit
again with a different hash. The stored commitment is then a value the player
chose AFTER seeing the target, which means it carries no information at all —
and `_result_proof` is bound to it.

The audit also asks for a SERVER salt at commit time, included in the proof, so
the binding rests on a value the client could not predict when it committed.
"""
from __future__ import annotations

import pytest

import match_engine as engine
from match_engine import MatchError, commit_intent, reveal_target


def _intent(tag: str) -> str:
    return "0x" + (tag * 32)[:64]


# --- the finding ------------------------------------------------------------
def test_recommit_after_window_is_rejected(active_match, addr, clock):
    """A commitment is FINAL. The window is not an escape hatch."""
    commit_intent(active_match, addr, 0, _intent("1"))
    clock.advance(engine.COMMIT_WINDOW_SECONDS + 1)

    with pytest.raises(MatchError, match="already committed"):
        commit_intent(active_match, addr, 0, _intent("2"))


def test_recommit_after_reveal_is_rejected(active_match, addr, clock):
    """The sharpest case: commit, SEE the target, then try to re-commit."""
    commit_intent(active_match, addr, 0, _intent("1"))
    reveal_target(active_match, addr, 0)
    clock.advance(engine.COMMIT_WINDOW_SECONDS + 1)

    with pytest.raises(MatchError, match="already committed"):
        commit_intent(active_match, addr, 0, _intent("2"))


def test_the_same_commit_is_still_idempotent(active_match, addr, clock):
    """A dropped HTTP response must not wedge the round."""
    commit_intent(active_match, addr, 0, _intent("1"))
    clock.advance(engine.COMMIT_WINDOW_SECONDS + 1)

    # Same hash: a retry, not a change.
    commit_intent(active_match, addr, 0, _intent("1"))


def test_the_commit_carries_a_server_salt(active_match, addr):
    """The binding must rest on a value the client could not predict."""
    commit_intent(active_match, addr, 0, _intent("1"))
    r = active_match.rounds[addr][0]

    salt = getattr(r, "commit_salt", "")
    assert salt, "the commit has no server salt (audit H2)"
    assert len(salt) >= 32, "the salt must be unguessable"


def test_two_commits_get_different_salts(active_match, addr, opp_addr):
    commit_intent(active_match, addr, 0, _intent("1"))
    commit_intent(active_match, opp_addr, 0, _intent("1"))

    assert active_match.rounds[addr][0].commit_salt != active_match.rounds[opp_addr][0].commit_salt


def test_the_result_proof_depends_on_the_salt(active_match, addr):
    """A proof issued for one commit must not validate for another."""
    commit_intent(active_match, addr, 0, _intent("1"))
    proof = reveal_target(active_match, addr, 0)["resultProof"]

    r = active_match.rounds[addr][0]
    # Swap the salt behind the proof — as a re-commit would have.
    r.commit_salt = "f" * 32

    recomputed = engine._result_proof(
        active_match.match_id, addr, 0, r.commit_hash, int(r.target_ms), r.commit_salt
    )
    assert recomputed != proof


def test_the_salt_is_required_by_the_proof(active_match, addr):
    """Without the salt the proof cannot be reproduced at all."""
    commit_intent(active_match, addr, 0, _intent("1"))
    reveal_target(active_match, addr, 0)
    r = active_match.rounds[addr][0]

    with pytest.raises(TypeError):
        engine._result_proof(active_match.match_id, addr, 0, r.commit_hash, int(r.target_ms))
