"""M31 — the server and client XP engines must agree, vector for vector.

Progression moved to the server (audit M31), which means the formula now exists
twice: `api/xp.py` (authoritative, what the ledger stores) and
`src/lib/xpSystem.ts` (what practice mode and the UI still compute). Two copies
of an economy formula drift silently — a player's level would depend on which
side of the wire you asked.

`tests/fixtures/xp_vectors.json` is the contract: the same inputs and the same
expected outputs, asserted by this test AND by
`src/lib/xpSystem.parity.test.ts`. A change on either side that is not mirrored
on the other fails a test instead of splitting the economy.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import xp

VECTORS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "xp_vectors.json"


@pytest.fixture(scope="module")
def vectors() -> list[dict]:
    return json.loads(VECTORS.read_text())


def test_the_vector_file_is_not_empty(vectors: list[dict]) -> None:
    assert len(vectors) >= 8, "the parity contract needs a real spread of inputs"


def test_server_xp_matches_every_vector(vectors: list[dict]) -> None:
    for v in vectors:
        got = xp.match_xp(
            v["outcome"],
            v["stake"],
            v["yourTimeMs"],
            v["currentXP"],
            v["winStreak"],
        )
        for key, expected in v["expected"].items():
            assert got[key] == expected, (
                f"api/xp.py disagrees with the client engine on {key} for {v}: "
                f"got {got[key]!r}, expected {expected!r}"
            )


def test_level_curve_is_the_inverse_of_the_threshold_curve() -> None:
    """`level_for_xp(xp_for_level(L)) == L` for every level in range."""
    for level in range(1, 60):
        assert xp.level_for_xp(xp.xp_for_level(level)) == level


def test_the_streak_bonus_can_actually_fire() -> None:
    """Audit M31: the streak bonus was dead — `winStreak` was never passed."""
    first = xp.match_xp("win", 1, 250, 0, win_streak=1)
    second = xp.match_xp("win", 1, 250, 0, win_streak=2)
    assert first["streakBonusXP"] == 0
    assert second["streakBonusXP"] == 30
