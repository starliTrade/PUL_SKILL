"""H-25 — a missing timestamp is not an ancient timestamp.

`settlement_deadline` used to compute

    max(getattr(match, "created_at", 0.0), getattr(match, "activated_at", 0.0) or 0.0)
    + MATCH_TIMEOUT_SECONDS

so a match WITHOUT either field produced `0 + 1800` = **1970-01-01 00:30 UTC**.
Two callers then did the worst possible thing with that number:

  * `oracle.sign_settlement` clamped the proof's deadline to 1800 and refused to
    sign with *"the on-chain MATCH_TIMEOUT has elapsed — this duel can only refund
    via refundTimeoutMatch"*. That message blames the contract for a missing
    field, and the winner's prize becomes unclaimable: the only way out is the
    refund, which pays both players and takes the win away.
  * the re-sign sweep compared `now >= 1800`, concluded "past the on-chain
    horizon", and skipped the match forever — silently, because a `continue` is
    not an error.

Both are reachable in production: `FirestoreStore.get()` rebuilds a `Match` from
a document, and a document written by an older schema (or a partially-written
one) simply has no `createdAt`. Nothing in the read path rejects it.

The fix separates "unknown" from "past": `settlement_deadline_or_none` returns
None, `settlement_deadline` raises with a message that names the cause, the
oracle signs without clamping (still bounded by its own 10-minute window) and the
sweep attempts the re-sign instead of giving up.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import main as server  # noqa: E402
import timebase  # noqa: E402

import match_engine as engine  # noqa: E402
import oracle  # noqa: E402


class _Match:
    """The minimum a settlement path touches (a dict-like Firestore rebuild)."""

    def __init__(self, **kw: Any) -> None:
        self.match_id = kw.pop("match_id", "0x" + "ab" * 32)
        for key, value in kw.items():
            setattr(self, key, value)


# --- the horizon itself -------------------------------------------------------


def test_a_match_without_timestamps_has_no_horizon() -> None:
    assert engine.settlement_deadline_or_none(_Match()) is None
    # And the strict accessor refuses instead of inventing 1970.
    with pytest.raises(ValueError) as err:
        engine.settlement_deadline(_Match())
    message = str(err.value)
    assert "createdAt" in message and "activatedAt" in message
    assert "settlement_deadline_or_none" in message


def test_a_zero_valued_timestamp_is_also_unknown() -> None:
    """`activated_at = 0` is normal for a duel that never paired — but if BOTH
    are zero, the record is telling us nothing, not telling us '1970'."""
    assert engine.settlement_deadline_or_none(_Match(created_at=0.0, activated_at=0.0)) is None


def test_the_horizon_still_uses_the_later_of_the_two() -> None:
    created, activated = 1_700_000_000.0, 1_700_000_500.0
    assert engine.settlement_deadline(
        _Match(created_at=created, activated_at=activated)
    ) == int(activated + engine.MATCH_TIMEOUT_SECONDS)
    assert engine.settlement_deadline(
        _Match(created_at=activated, activated_at=created)
    ) == int(activated + engine.MATCH_TIMEOUT_SECONDS)


# --- the sweep must not abandon a winner -------------------------------------


def test_an_unknown_horizon_is_not_treated_as_past() -> None:
    """The exact bug: `now >= 1800` is always true, so the sweep skipped it."""
    assert server._past_settlement_horizon(_Match()) is False


def test_a_real_horizon_in_the_future_is_not_past() -> None:
    now = timebase.now()
    assert server._past_settlement_horizon(
        _Match(created_at=now, activated_at=now)
    ) is False


def test_a_real_horizon_in_the_past_is_past() -> None:
    long_ago = timebase.now() - engine.MATCH_TIMEOUT_SECONDS - 60
    assert server._past_settlement_horizon(
        _Match(created_at=long_ago, activated_at=long_ago)
    ) is True


def test_the_sweep_uses_the_predicate_rather_than_calling_the_strict_accessor() -> None:
    """`settlement_deadline` raises now, so a direct call inside the sweep would
    abort the whole pass (its outer `except` counts one failure and stops). The
    sweep must go through the None-aware helper."""
    import io  # noqa: PLC0415
    import tokenize  # noqa: PLC0415

    source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    # Comments and docstrings are prose — they may QUOTE the old call to explain
    # it. Only executable code counts.
    code = "".join(
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING)
    )
    assert "engine.settlement_deadline(m)" not in code, (
        "the sweep still calls the raising accessor — one untimestamped match "
        "would abort the pass for every other winner"
    )
    # The helper is the only place that computes a horizon; both call sites share it.
    assert code.count("engine.settlement_deadline_or_none(m)") == 1
    assert code.count("_past_settlement_horizon(m)") == 2


# --- the oracle must still sign ----------------------------------------------


class _Record(dict):
    pass


def _engine_shaped_record(monkeypatch: pytest.MonkeyPatch, match_id: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": "settled",
        "matchId": match_id,
        "winner": "0x" + "11" * 20,
        "winnerTimeMs": 220,
        "loserTimeMs": 310,
        "validatedTimes": {
            "0x" + "11" * 20: [220.0],
            "0x" + "22" * 20: [310.0],
        },
    }
    engine.stamp_settlement(record)
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", "0x" + "33" * 32)
    monkeypatch.setenv("ESCROW_ADDRESS", "0x" + "ab" * 20)
    monkeypatch.setenv("ORACLE_CHAIN_ID", "80002")
    return record


def test_the_oracle_signs_without_clamping_when_the_horizon_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusing to sign strands a real winner; a 10-minute proof is still safe.

    Measured before the fix: `sign_settlement(record, matchish=<no timestamps>)`
    raised `ValueError: Refusing to sign: the on-chain MATCH_TIMEOUT has elapsed`.
    """
    monkeypatch.setattr(oracle, "SETTLEMENT_DEADLINE_SECONDS", 600)
    match = _Match()
    record = _engine_shaped_record(monkeypatch, str(match.match_id))

    envelope = oracle.sign_settlement(record, matchish=match)

    now = int(timebase.now())
    assert envelope["deadline"] >= now, "the proof was minted already expired"
    assert envelope["deadline"] <= now + 600 + 5
    assert envelope["signature"].startswith("0x")


def test_the_oracle_still_clamps_when_the_horizon_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oracle, "SETTLEMENT_DEADLINE_SECONDS", 600)
    activated = timebase.now() - engine.MATCH_TIMEOUT_SECONDS + 60  # 60 s left
    match = _Match(created_at=activated, activated_at=activated)
    record = _engine_shaped_record(monkeypatch, str(match.match_id))

    envelope = oracle.sign_settlement(record, matchish=match)

    horizon = int(activated + engine.MATCH_TIMEOUT_SECONDS)
    assert envelope["deadline"] <= horizon, (
        "the clamp no longer bounds the proof by the refund horizon"
    )
