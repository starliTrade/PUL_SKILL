"""Server-authoritative progression (audit M31).

Wins, XP, level and win-streak used to live entirely in the client's
localStorage: any player could edit them, and `winStreak` was never passed to
the XP calculation at all — the streak bonus documented in the client engine
was dead code that could never fire. Progression is now computed and stored by
the server, in the same transaction as the settlement, and read back by the
client.

The formula mirrors `src/lib/xpSystem.ts` exactly. `tests/unit/test_xp_parity.py`
pins both implementations to the same vectors, so changing one side without the
other fails a test instead of silently splitting the economy.
"""

from __future__ import annotations

import math
from typing import Any

WIN_BASE_XP = 120
LOSS_BASE_XP = 35
WIN_STAKE_MULTIPLIER = 25
LOSS_STAKE_MULTIPLIER = 10
STAKE_BONUS_CAP = 250
# (reaction ceiling in ms, bonus) — first match wins, mirroring the client.
SPEED_BONUSES: tuple[tuple[float, int], ...] = ((180, 60), (240, 35), (300, 20))
STREAK_XP_PER_WIN = 15
STREAK_BONUS_CAP = 75


def _js_round(value: float) -> int:
    """JavaScript's `Math.round`: half UP, not Python's banker's rounding.

    `round(0.5)` is 0 in Python and 1 in JS. Every XP number crosses this
    boundary eventually, and a one-point drift per match is a drift the parity
    test would catch but the economy would already have paid out.
    """
    return math.floor(value + 0.5)


def xp_for_level(level: int) -> int:
    """Total XP required to REACH `level` (mirrors XPSystem.getXPForLevel)."""
    if level <= 1:
        return 0
    return _js_round(100 * math.pow(level - 1, 1.5))


def level_for_xp(total_xp: float) -> int:
    """The level a total XP amount corresponds to (mirrors XPSystem.getLevel)."""
    if total_xp <= 0:
        return 1
    level = math.floor(math.pow(total_xp / 100, 1 / 1.5)) + 1
    while xp_for_level(level + 1) <= total_xp:
        level += 1
    while level > 1 and xp_for_level(level) > total_xp:
        level -= 1
    return max(1, level)


def match_xp(
    outcome: str,
    stake: float,
    your_time_ms: float,
    current_xp: float,
    win_streak: int = 0,
) -> dict[str, Any]:
    """XP for one settled duel (mirrors XPSystem.calculateMatchXP).

    `win_streak` is the streak INCLUDING this match: the first win of a streak
    earns no streak bonus, the second earns one, and so on up to the cap.
    """
    if outcome == "void":
        return {
            "baseXP": 0,
            "stakeBonusXP": 0,
            "speedBonusXP": 0,
            "streakBonusXP": 0,
            "totalAwardedXP": 0,
            "newTotalXP": current_xp,
            "newLevel": level_for_xp(current_xp),
        }

    won = outcome == "win"
    base_xp = WIN_BASE_XP if won else LOSS_BASE_XP
    stake_bonus = _js_round(
        min(stake * (WIN_STAKE_MULTIPLIER if won else LOSS_STAKE_MULTIPLIER), STAKE_BONUS_CAP)
    )

    speed_bonus = 0
    if won and your_time_ms > 0:
        for ceiling, bonus in SPEED_BONUSES:
            if your_time_ms < ceiling:
                speed_bonus = bonus
                break

    streak_bonus = 0
    if won and win_streak > 1:
        streak_bonus = min(win_streak * STREAK_XP_PER_WIN, STREAK_BONUS_CAP)

    total = base_xp + stake_bonus + speed_bonus + streak_bonus
    new_total = current_xp + total
    return {
        "baseXP": base_xp,
        "stakeBonusXP": stake_bonus,
        "speedBonusXP": speed_bonus,
        "streakBonusXP": streak_bonus,
        "totalAwardedXP": total,
        "newTotalXP": new_total,
        "newLevel": level_for_xp(new_total),
    }


__all__ = ["level_for_xp", "match_xp", "xp_for_level"]
