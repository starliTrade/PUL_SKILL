/**
 * PULSAR — the XP engine.
 *
 * Audit 2026-10-13: this header used to describe a product that does not exist —
 * a "$PULSAR" token, a "Fixed Base Mining Rate (100 XP = 1 $PULSAR)", tier
 * "yield boosts", a "Biometric Entropy Threshold >= 80%", and an "Anti-Farming
 * Cooldown". `TOKENOMICS_SPEC` was deleted precisely because there is no token,
 * and H16 removed the fabricated biometric claims from the anti-cheat module —
 * but this block kept advertising all of it at the top of the file.
 *
 * What the engine actually does: converts a settled duel's outcome, stake and
 * reaction time into XP, and XP into a level. The server owns the numbers
 * (`api/xp.py`); this copy is for practice mode and for describing a total the
 * client did not compute. `tests/fixtures/xp_vectors.json` pins the two together.
 *
 * 1. Leveling Curve:
 *    - XP Required for Level L: Threshold(L) = round(100 * (L - 1)^1.5)
 *    - Level 1: 0 XP
 *    - Level 2: 100 XP
 *    - Level 5: 800 XP
 *    - Level 10: 2,700 XP
 *    - Level 25: 11,757 XP
 *    - Level 50: 34,300 XP (Apex Predator Tier)
 *
 * 2. Match Reward Matrix (audit M31: these are the numbers the code uses —
 *    `api/xp.py` mirrors them and `tests/fixtures/xp_vectors.json` pins the two
 *    together. This block used to document a DIFFERENT matrix than the one
 *    implemented, which is exactly the drift the parity contract exists to
 *    prevent):
 *    - Base Victory XP: +120 XP
 *    - Base Loss XP: +35 XP (Encourages active duel participation)
 *    - Stake Weight Multiplier: +round(min(stake * 25, 250)) XP on a win,
 *      +round(min(stake * 10, 250)) XP on a loss
 *    - Reflex Speed Bonus (wins only):
 *      * Sub-180ms: +60 XP (Peak Human Reflex)
 *      * Sub-240ms: +35 XP (Elite Reflex)
 *      * Sub-300ms: +20 XP (Fast Reflex)
 *    - Streak Multiplier: +min(winStreak * 15, 75) XP, where `winStreak` is the
 *      streak INCLUDING this win (so the first win of a streak earns none)
 *
 * 3. Tiers: cosmetic bands over the level curve (Novice / Veteran / Cyber Master
 *    / Apex Predator). They carry NO economic multiplier — there is no token to
 *    multiply. `tierMultiplier` is kept because the UI renders it as a label.
 */

export interface XPSummary {
  baseXP: number;
  stakeBonusXP: number;
  speedBonusXP: number;
  streakBonusXP: number;
  totalAwardedXP: number;
  newTotalXP: number;
  newLevel: number;
  currentLevelXP: number;
  nextLevelThresholdXP: number;
  levelProgressPercent: number;
  tierName: string;
  tierMultiplier: number;
}

export interface TierInfo {
  tier: number;
  name: string;
  multiplier: number;
  color: string;
  bgColor: string;
  borderColor: string;
  badge: string;
  minLevel: number;
  maxLevel: number;
  description: string;
}

// P0.10 — REMOVED: TOKENOMICS_SPEC. There is no $PULSAR token. Displaying a
// token supply, distribution, staking APY, and "mining yield" for an asset that
// does not exist is a fabricated financial claim, not a feature.

export class XPSystem {
  public static getLevel(totalXP: number): number {
    if (totalXP <= 0) return 1;
    // Audit M45: this floors while `getXPForLevel` rounds, so the two were not
    // inverses — a player at exactly the XP for level 5 was shown as level 4.
    // The estimate below is then corrected against the real thresholds, which
    // makes the pair exact by construction.
    let level = Math.floor(Math.pow(totalXP / 100, 1 / 1.5)) + 1;
    while (this.getXPForLevel(level + 1) <= totalXP) level++;
    while (level > 1 && this.getXPForLevel(level) > totalXP) level--;
    return Math.max(1, level);
  }

  public static getXPForLevel(level: number): number {
    if (level <= 1) return 0;
    return Math.round(100 * Math.pow(level - 1, 1.5));
  }

  public static getTierInfo(level: number): TierInfo {
    if (level >= 50) {
      return {
        tier: 4,
        name: 'Apex Predator',
        multiplier: 2.0,
        color: 'text-amber-400',
        bgColor: 'bg-amber-500/10',
        borderColor: 'border-amber-500/25',
        badge: 'Tier IV',
        minLevel: 50,
        maxLevel: 999,
        description: 'Elite reflex master with grandmaster tournament access.',
      };
    }
    if (level >= 26) {
      return {
        tier: 3,
        name: 'Cyber Master',
        multiplier: 1.5,
        color: 'text-purple-400',
        bgColor: 'bg-purple-500/10',
        borderColor: 'border-purple-500/25',
        badge: 'Tier III',
        minLevel: 26,
        maxLevel: 49,
        description: 'Master duelist with access to high-roller arenas.',
      };
    }
    if (level >= 11) {
      return {
        tier: 2,
        name: 'Veteran Duelist',
        multiplier: 1.25,
        color: 'text-sky-400',
        bgColor: 'bg-sky-500/10',
        borderColor: 'border-sky-500/25',
        badge: 'Tier II',
        minLevel: 11,
        maxLevel: 25,
        description: 'Experienced fighter with a hardened reaction curve.',
      };
    }
    return {
      tier: 1,
      name: 'Novice Duelist',
      multiplier: 1.0,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/25',
      badge: 'Tier I',
      minLevel: 1,
      maxLevel: 10,
      description: 'The starting tier for emerging players.',
    };
  }

  public static getTier(level: number): TierInfo {
    return this.getTierInfo(level);
  }

  public static getLevelProgress(totalXP: number): number {
    const curLevel = this.getLevel(totalXP);
    const curBase = this.getXPForLevel(curLevel);
    const nextBase = this.getXPForLevel(curLevel + 1);
    const span = Math.max(1, nextBase - curBase);
    const inLevel = totalXP - curBase;
    return Math.min(100, Math.max(0, Math.round((inLevel / span) * 100)));
  }

  public static getXPToNextLevel(totalXP: number): { inLevel: number; span: number } {
    const curLevel = this.getLevel(totalXP);
    const curBase = this.getXPForLevel(curLevel);
    const nextBase = this.getXPForLevel(curLevel + 1);
    const span = Math.max(1, nextBase - curBase);
    const inLevel = Math.max(0, totalXP - curBase);
    return { inLevel, span };
  }

  public static calculateMatchXP(
    outcome: 'win' | 'loss' | 'void',
    stake: number,
    yourTimeMs: number,
    currentXP: number,
    winStreak: number = 0
  ): XPSummary {
    if (outcome === 'void') {
      const curLvl = this.getLevel(currentXP);
      const curLvlBase = this.getXPForLevel(curLvl);
      const nextLvlBase = this.getXPForLevel(curLvl + 1);
      const span = Math.max(1, nextLvlBase - curLvlBase);
      const inLevel = currentXP - curLvlBase;
      const progress = Math.min(100, Math.round((inLevel / span) * 100));
      const tier = this.getTierInfo(curLvl);

      return {
        baseXP: 0,
        stakeBonusXP: 0,
        speedBonusXP: 0,
        streakBonusXP: 0,
        totalAwardedXP: 0,
        newTotalXP: currentXP,
        newLevel: curLvl,
        currentLevelXP: Math.max(0, inLevel),
        nextLevelThresholdXP: span,
        levelProgressPercent: Math.max(0, progress),
        tierName: tier.name,
        tierMultiplier: tier.multiplier,
      };
    }

    const baseXP = outcome === 'win' ? 120 : 35;
    const stakeBonusXP = Math.round(Math.min(stake * (outcome === 'win' ? 25 : 10), 250));

    let speedBonusXP = 0;
    if (outcome === 'win' && yourTimeMs > 0) {
      if (yourTimeMs < 180) {
        speedBonusXP = 60; // Peak Reflex Bonus
      } else if (yourTimeMs < 240) {
        speedBonusXP = 35; // Elite Reflex
      } else if (yourTimeMs < 300) {
        speedBonusXP = 20; // Fast Reflex
      }
    }

    let streakBonusXP = 0;
    if (outcome === 'win' && winStreak > 1) {
      streakBonusXP = Math.min(winStreak * 15, 75);
    }

    const totalAwardedXP = baseXP + stakeBonusXP + speedBonusXP + streakBonusXP;
    const newTotalXP = currentXP + totalAwardedXP;

    return {
      baseXP,
      stakeBonusXP,
      speedBonusXP,
      streakBonusXP,
      totalAwardedXP,
      ...this.describe(newTotalXP),
    };
  }

  /**
   * The level/progress/tier a total XP amount implies.
   *
   * Audit M31: the server owns XP now, so the client must be able to describe a
   * total it did not compute. Without this the post-match screen would show the
   * server's LEVEL next to a progress bar derived from the local estimate — two
   * numbers from different ledgers, side by side.
   */
  public static describe(totalXP: number, levelOverride?: number): {
    newTotalXP: number;
    newLevel: number;
    currentLevelXP: number;
    nextLevelThresholdXP: number;
    levelProgressPercent: number;
    tierName: string;
    tierMultiplier: number;
  } {
    // The server's level wins when it is supplied: it is the authority, and the
    // parity test pins the two curves together so a disagreement is a bug
    // rather than a legitimate difference.
    const newLevel = levelOverride && levelOverride > 0 ? levelOverride : this.getLevel(totalXP);
    const curLevelBaseXP = this.getXPForLevel(newLevel);
    const nextLevelBaseXP = this.getXPForLevel(newLevel + 1);
    const xpSpan = Math.max(1, nextLevelBaseXP - curLevelBaseXP);
    const currentInLevel = totalXP - curLevelBaseXP;
    const progressPercent = Math.min(100, Math.round((currentInLevel / xpSpan) * 100));
    const tier = this.getTierInfo(newLevel);
    return {
      newTotalXP: totalXP,
      newLevel,
      currentLevelXP: Math.max(0, currentInLevel),
      nextLevelThresholdXP: xpSpan,
      levelProgressPercent: Math.max(0, progressPercent),
      tierName: tier.name,
      tierMultiplier: tier.multiplier,
    };
  }
}
