"""H8 regression — the sweep must not void a match that is ready to settle.

Audit H8: `sweep_expired` voided every ACTIVE match past `MATCH_EXPIRY_SECONDS`
(10 minutes) outright. But by then the settle grace window (8 minutes) has also
passed, which means `match_completed()` is TRUE — the missing rounds are
forfeits and the match is exactly what the settlement path exists for. Voiding
it destroys the winner's prize: `settle()` then refuses ("Match is not active"),
no oracle signature is ever minted, and both players get only a refund — even
though the escrow would still honour a settlement for another 20 minutes.

The same applies to a match where both players genuinely finished all rounds:
the sweep could void a fully-played duel before anyone polled the match view.

Correct behaviour:
  - WAITING past QUEUE_EXPIRY            -> void (nobody paired; nothing to settle)
  - ACTIVE  past MATCH_EXPIRY, completed -> do NOT void; hand it to the finalizer
  - ACTIVE  past MATCH_EXPIRY, incomplete-> do NOT void either: the grace window
                                            has passed, so it is a forfeit
                                            settlement, not an abandonment
"""

from __future__ import annotations

import pytest

import match_engine as engine
from store import InMemoryStore


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def _active_match(store: InMemoryStore, addr: str, opp: str, *, activated_at: float) -> engine.Match:
    match = store.enqueue(addr, 1.0)
    store.enqueue(opp, 1.0)
    assert match.status == "active"
    match.activated_at = activated_at
    return match


def _play_all(match: engine.Match, addr: str, base_ms: float) -> None:
    import hashlib

    for idx in range(engine.ROUNDS):
        engine.commit_intent(
            match, addr, idx, "0x" + hashlib.sha256(f"{addr}{idx}".encode()).hexdigest()
        )
        target = engine.reveal_target(match, addr, idx)
        r = match.rounds[addr.lower()][idx]
        r.revealed_at -= (r.target_ms + base_ms + idx) / 1000.0
        engine.submit_result(match, addr, idx, base_ms + idx, target["resultProof"])


def test_waiting_match_past_queue_expiry_is_still_voided(store, clock):
    """The sweep's original job — unpaired matches — must keep working."""
    match = store.enqueue("0x" + "11" * 20, 1.0)
    clock.advance(engine.QUEUE_EXPIRY_SECONDS + 60)
    store.sweep_expired()
    assert match.status == "void"


def test_fully_played_match_is_not_voided_by_the_sweep(store, clock):
    """Both players finished: this is a settlement, not an abandonment."""
    addr, opp = "0x" + "11" * 20, "0x" + "22" * 20
    match = _active_match(store, addr, opp, activated_at=clock.value)
    _play_all(match, addr, 220.0)
    _play_all(match, opp, 300.0)
    assert engine.match_completed(match) is True

    clock.advance(engine.MATCH_EXPIRY_SECONDS + 60)
    store.sweep_expired()

    assert match.status != "void", (
        "the sweep voided a fully-played match — the winner's prize is gone and "
        "settle() now refuses (audit H8)"
    )


def test_abandoned_match_past_play_expiry_is_not_voided(store, clock):
    """Past MATCH_EXPIRY the grace window has also passed -> forfeit settlement."""
    addr, opp = "0x" + "11" * 20, "0x" + "22" * 20
    match = _active_match(store, addr, opp, activated_at=clock.value)
    _play_all(match, addr, 220.0)  # only one side played

    clock.advance(engine.MATCH_EXPIRY_SECONDS + 60)
    assert engine.match_completed(match) is True, "grace window should have passed"

    store.sweep_expired()

    assert match.status != "void", (
        "the sweep voided an abandoned-but-settleable match instead of leaving "
        "it for the forfeit settlement (audit H8)"
    )


def test_sweep_returns_the_matches_that_need_finalizing(store, clock):
    """The caller must be told what to settle — the store has no engine logic."""
    addr, opp = "0x" + "11" * 20, "0x" + "22" * 20
    match = _active_match(store, addr, opp, activated_at=clock.value)
    _play_all(match, addr, 220.0)

    clock.advance(engine.MATCH_EXPIRY_SECONDS + 60)
    due = store.sweep_expired()

    assert isinstance(due, list), "sweep_expired must return the due matches"
    assert match.match_id in [m.match_id for m in due], (
        "a settleable match past its play expiry must be handed to the finalizer"
    )
