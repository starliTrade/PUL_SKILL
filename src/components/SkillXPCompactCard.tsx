import React from 'react';
import { XPSystem, TierInfo } from '../lib/xpSystem';
import { PulsarStarIcon } from './PulsarLogo';
import { cn } from '../lib/utils';

interface SkillXPCompactCardProps {
  xp: number;
  level: number;
  className?: string;
}

export const SkillXPCompactCard: React.FC<SkillXPCompactCardProps> = ({
  xp,
  level,
  className,
}) => {
  const tier: TierInfo = XPSystem.getTierInfo(level);

  const curLevelBaseXP = XPSystem.getXPForLevel(level);
  const nextLevelBaseXP = XPSystem.getXPForLevel(level + 1);
  const span = Math.max(1, nextLevelBaseXP - curLevelBaseXP);
  const inLevel = Math.max(0, xp - curLevelBaseXP);
  const progressPercent = Math.min(100, Math.max(0, Math.round((inLevel / span) * 100)));

  return (
    <div
      className={cn(
        'p-3 rounded-xl bg-zinc-950/80 border border-white/[0.06] relative overflow-hidden',
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        {/* Left: Level and Tier Badge */}
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300 shrink-0">
            <PulsarStarIcon size={13} glow={false} showFlare={false} />
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-zinc-200">
                Level {level}
              </span>
              <span className="text-[9px] font-mono text-zinc-400 bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06]">
                {tier.name}
              </span>
            </div>
          </div>
        </div>

        {/* Right: XP */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="text-right">
            <div className="text-[11px] font-mono text-zinc-300 font-semibold">
              {inLevel.toLocaleString()} / {span.toLocaleString()} <span className="text-zinc-500 font-normal">XP</span>
            </div>
          </div>
        </div>
      </div>

      {/* Level Progress Bar */}
      <div className="mt-2 space-y-1">
        <div className="w-full bg-zinc-800/60 rounded-full h-1 overflow-hidden">
          <div
            style={{ width: `${progressPercent}%` }}
            className="h-full bg-zinc-300 rounded-full transition-all duration-500"
          />
        </div>
        <div className="flex justify-between items-center text-[9px] text-zinc-500 font-mono">
          <span>{progressPercent}% to Lv {level + 1}</span>
        </div>
      </div>
    </div>
  );
};
