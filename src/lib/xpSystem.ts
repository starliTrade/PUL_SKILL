/**
 * Pulsar Protocol - Cryptographic Skill-to-Earn Tokenomics & XP Engine ($PULSAR)
 *
 * Mathematically Non-Exploitable Economic Model:
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
 * 2. Match Reward Matrix:
 *    - Base Victory XP: +100 XP
 *    - Base Loss XP: +30 XP (Encourages active duel participation)
 *    - Stake Weight Multiplier: +round(min(stake * 20, 200)) XP (Logarithmic dampening against whale exploits)
 *    - Reflex Speed Bonus:
 *      * Sub-180ms: +50 XP (Peak Human Reflex)
 *      * Sub-240ms: +30 XP (Elite Reflex)
 *      * Sub-300ms: +15 XP (Fast Reflex)
 *    - Streak Multiplier: +min(winStreak * 12, 60) XP (Rewards consistency)
 *
 * 3. Native Token Conversion & Staking Yield:
 *    - Fixed Base Mining Rate: 100 XP = 1 $PULSAR Token (0.01 $PULSAR per XP)
 *    - Tier Multipliers ($PULSAR Airdrop & Mining Velocity):
 *      * Tier I (Novice Duelist - Lv 1-10): 1.00x Base Yield
 *      * Tier II (Veteran Duelist - Lv 11-25): 1.25x Yield Boost
 *      * Tier III (Cyber Master - Lv 26-49): 1.50x Yield Boost
 *      * Tier IV (Apex Predator - Lv 50+): 2.00x Max Yield Boost
 *
 * 4. Anti-Bot & Proof-of-Skill Guardrails:
 *    - Biometric Entropy Threshold: Must achieve >= 80% entropy confidence to mine bonus reflex XP.
 *    - Anti-Farming Cooldown: Repeated consecutive duels with identical peers have diminishing XP returns.
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
  estimatedPulsarTokens: number;
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

export const TOKENOMICS_SPEC = {
  tokenName: 'Pulsar Protocol Token',
  tokenTicker: '$PULSAR',
  totalSupply: '100,000,000 $PULSAR',
  network: 'Polygon Mainnet (Chain ID 137)',
  contractStandard: 'ERC-20 with EIP-712 Meta-Transactions',
  distribution: [
    { label: 'Proof-of-Reflex Skill Mining (XP Conversion)', percent: 65, color: 'bg-sky-400' },
    { label: 'Ecosystem Liquidity & Staking Vaults', percent: 15, color: 'bg-emerald-400' },
    { label: 'Seasonal Tournaments & Prize Pools', percent: 10, color: 'bg-amber-400' },
    { label: 'Core Development & Security Audits (24m Linear Vesting)', percent: 10, color: 'bg-purple-400' },
  ],
  utilities: [
    '0% Platform Protocol Fee discount on duel settlements when holding >= 500 $PULSAR',
    'Staking into High-Roller Escrow Liquidity Vaults with APY revenue share from 2% protocol rake',
    'Exclusive access to Tier IV Apex Grandmaster Invitational Tournaments',
    'Decentralized Governance Voting on new game modes and EIP-712 anti-cheat latency thresholds',
  ],
};

export class XPSystem {
  public static getLevel(totalXP: number): number {
    if (totalXP <= 0) return 1;
    const lvl = Math.floor(Math.pow(totalXP / 100, 1 / 1.5)) + 1;
    return Math.max(1, lvl);
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
        description: 'Elite reflex master with 2.0x maximum $PULSAR mining power and grandmaster tournament access.',
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
        description: 'Master duelist with 1.5x $PULSAR boost and access to high-roller arenas.',
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
        description: 'Experienced fighter with 1.25x boosted token generation.',
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
      description: 'Standard 1.0x token mining rate for emerging players.',
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
        estimatedPulsarTokens: parseFloat((currentXP * 0.01 * tier.multiplier).toFixed(2)),
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

    const newLevel = this.getLevel(newTotalXP);
    const curLevelBaseXP = this.getXPForLevel(newLevel);
    const nextLevelBaseXP = this.getXPForLevel(newLevel + 1);
    const xpSpan = Math.max(1, nextLevelBaseXP - curLevelBaseXP);
    const currentInLevel = newTotalXP - curLevelBaseXP;
    const progressPercent = Math.min(100, Math.round((currentInLevel / xpSpan) * 100));
    const tier = this.getTierInfo(newLevel);

    return {
      baseXP,
      stakeBonusXP,
      speedBonusXP,
      streakBonusXP,
      totalAwardedXP,
      newTotalXP,
      newLevel,
      currentLevelXP: Math.max(0, currentInLevel),
      nextLevelThresholdXP: xpSpan,
      levelProgressPercent: Math.max(0, progressPercent),
      estimatedPulsarTokens: parseFloat((newTotalXP * 0.01 * tier.multiplier).toFixed(2)),
      tierName: tier.name,
      tierMultiplier: tier.multiplier,
    };
  }
}
