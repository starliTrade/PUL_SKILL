import React from 'react';
import { cn } from '../lib/utils';

export type PulsarAvatarTier = 'novice' | 'veteran' | 'master' | 'apex' | 'grandmaster';

export interface PulsarAvatarProps {
  level?: number;
  xp?: number;
  tierOverride?: PulsarAvatarTier;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  showBadge?: boolean;
  glow?: boolean;
  interactive?: boolean;
  onClick?: () => void;
}

const sizeConfig = {
  xs: { box: 'w-6 h-6 rounded-lg', star: 16, border: 'border' },
  sm: { box: 'w-8 h-8 rounded-xl', star: 22, border: 'border' },
  md: { box: 'w-10 h-10 rounded-xl', star: 28, border: 'border' },
  lg: { box: 'w-12 h-12 rounded-xl', star: 34, border: 'border' },
  xl: { box: 'w-16 h-16 rounded-2xl', star: 46, border: 'border' },
};

/**
 * 5 Refined Pulsar Star Tiers:
 * - Novice (Unconnected / Level 1-10): Pure Platinum Silver & Clean White
 * - Veteran (Level 11-25): Emerald Matrix
 * - Cyber Master (Level 26-49): Solar Amber Gold
 * - Apex Predator (Level 50-74): Electric Sky Blue (Brand Color)
 * - Grandmaster (Level 75+): Hyper Violet-Indigo
 */
export const AVATAR_STAGES = [
  { lvl: 1, name: 'Novice Duelist', colorName: 'Platinum White', description: 'Clean metallic baseline' },
  { lvl: 11, name: 'Veteran Clash', colorName: 'Emerald Matrix', description: 'Reaction & speed hardened' },
  { lvl: 26, name: 'Cyber Master', colorName: 'Solar Amber Gold', description: 'Apex reflex unlocked' },
  { lvl: 50, name: 'Apex Predator', colorName: 'Electric Sky Blue', description: 'Signature Pulsar star' },
  { lvl: 75, name: 'Grandmaster Pulsar', colorName: 'Hyper Blue-Violet', description: 'Singularity quantum tier' },
];

export function getAvatarTier(level: number): {
  key: PulsarAvatarTier;
  name: string;
  colorName: string;
  theme: {
    coreColor: string;
    beamColor1: string;
    beamColor2: string;
    border: string;
    bg: string;
    glowShadow: string;
    text: string;
    badgeBg: string;
    badgeText: string;
    ringColor: string;
    hex: string;
  };
} {
  if (level >= 75) {
    return {
      key: 'grandmaster',
      name: 'Grandmaster Pulsar',
      colorName: 'Hyper Blue-Violet',
      theme: {
        coreColor: '#38bdf8',
        beamColor1: '#6366f1',
        beamColor2: '#a855f7',
        border: 'border-purple-400/30 hover:border-purple-400/50',
        bg: 'bg-zinc-950/65 backdrop-blur-2xl',
        glowShadow: 'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06),0_0_15px_rgba(168,85,247,0.18)]',
        text: 'text-purple-400',
        badgeBg: 'bg-purple-950/80 border-purple-500/40',
        badgeText: 'text-purple-300',
        ringColor: 'ring-purple-400/30',
        hex: '#a855f7',
      },
    };
  }

  if (level >= 50) {
    return {
      key: 'apex',
      name: 'Apex Predator',
      colorName: 'Electric Sky Blue',
      theme: {
        coreColor: '#bae6fd',
        beamColor1: '#38bdf8',
        beamColor2: '#0284c7',
        border: 'border-sky-400/30 hover:border-sky-400/50',
        bg: 'bg-zinc-950/65 backdrop-blur-2xl',
        glowShadow: 'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06),0_0_15px_rgba(56,189,248,0.18)]',
        text: 'text-sky-400',
        badgeBg: 'bg-sky-950/80 border-sky-500/40',
        badgeText: 'text-sky-300',
        ringColor: 'ring-sky-400/30',
        hex: '#38bdf8',
      },
    };
  }

  if (level >= 26) {
    return {
      key: 'master',
      name: 'Cyber Master',
      colorName: 'Solar Amber Gold',
      theme: {
        coreColor: '#fef3c7',
        beamColor1: '#fbbf24',
        beamColor2: '#d97706',
        border: 'border-amber-400/30 hover:border-amber-400/50',
        bg: 'bg-zinc-950/65 backdrop-blur-2xl',
        glowShadow: 'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06),0_0_15px_rgba(251,191,36,0.18)]',
        text: 'text-amber-400',
        badgeBg: 'bg-amber-950/80 border-amber-500/40',
        badgeText: 'text-amber-300',
        ringColor: 'ring-amber-400/30',
        hex: '#fbbf24',
      },
    };
  }

  if (level >= 11) {
    return {
      key: 'veteran',
      name: 'Veteran Duelist',
      colorName: 'Emerald Matrix',
      theme: {
        coreColor: '#d1fae5',
        beamColor1: '#34d399',
        beamColor2: '#059669',
        border: 'border-emerald-400/30 hover:border-emerald-400/50',
        bg: 'bg-zinc-950/65 backdrop-blur-2xl',
        glowShadow: 'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06),0_0_15px_rgba(52,211,153,0.18)]',
        text: 'text-emerald-400',
        badgeBg: 'bg-emerald-950/80 border-emerald-500/40',
        badgeText: 'text-emerald-300',
        ringColor: 'ring-emerald-400/30',
        hex: '#34d399',
      },
    };
  }

  // Novice / Unconnected (Pure Platinum White & Clean Metallic Neutral)
  return {
    key: 'novice',
    name: 'Novice Duelist',
    colorName: 'Platinum White',
    theme: {
      coreColor: '#ffffff',
      beamColor1: '#f4f4f5', // Crisp silver-white
      beamColor2: '#a1a1aa', // Platinum zinc
      border: 'border-white/[0.08] hover:border-white/[0.15]',
      bg: 'bg-zinc-950/65 backdrop-blur-2xl',
      glowShadow: 'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)]',
      text: 'text-zinc-200',
      badgeBg: 'bg-zinc-900 border-white/[0.08]',
      badgeText: 'text-zinc-300',
      ringColor: 'ring-white/20',
      hex: '#ffffff',
    },
  };
}

/**
 * Pulsar Dynamic Avatar Component
 */
export const PulsarDynamicAvatar: React.FC<PulsarAvatarProps> = ({
  level = 1,
  size = 'md',
  className,
  showBadge = true,
  interactive = false,
  onClick,
}) => {
  const tier = getAvatarTier(level);
  const cfg = sizeConfig[size];
  const rawId = React.useId();
  const id = rawId.replace(/[^a-zA-Z0-9]/g, '');

  const singularityId = `av10-sing-${id}`;
  const coreJetBeamId = `av10-jet-${id}`;
  const plasmaSheathId = `av10-sheath-${id}`;
  const optMicroId = `av10-micro-${id}`;
  const optSubtleId = `av10-subtle-${id}`;
  const optBloomId = `av10-bloom-${id}`;

  return (
    <div
      onClick={onClick}
      className={cn(
        'relative inline-flex items-center justify-center select-none shrink-0',
        interactive && 'cursor-pointer hover:scale-105 transition-transform',
        className
      )}
    >
      {/* Outer Glow Box Container with Clean Dark Glass */}
      <div
        className={cn(
          'relative flex items-center justify-center overflow-hidden transition-all duration-300',
          cfg.box,
          cfg.border,
          tier.theme.border,
          tier.theme.bg,
          tier.theme.glowShadow
        )}
      >
        {/* Subtle Ambient Backlight */}
        <div
          className="absolute inset-0 opacity-20 pointer-events-none"
          style={{
            background: `radial-gradient(circle at 50% 50%, ${tier.theme.beamColor1} 0%, transparent 75%)`,
          }}
        />

        {/* Dynamic Pulsar Star SVG Mark */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 800 800"
          width={cfg.star}
          height={cfg.star}
          className="shrink-0 overflow-visible relative z-10 select-none"
        >
          <defs>
            <radialGradient id={singularityId} cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={tier.theme.coreColor} stopOpacity={1} />
              <stop offset="10%" stopColor={tier.theme.beamColor1} stopOpacity={0.85} />
              <stop offset="35%" stopColor={tier.theme.beamColor2} stopOpacity={0.4} />
              <stop offset="70%" stopColor="#000000" stopOpacity={0.05} />
              <stop offset="100%" stopColor="#000000" stopOpacity={0} />
            </radialGradient>

            <linearGradient id={coreJetBeamId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={tier.theme.beamColor2} stopOpacity={0} />
              <stop offset="25%" stopColor={tier.theme.beamColor2} stopOpacity={0.3} />
              <stop offset="45%" stopColor={tier.theme.beamColor1} stopOpacity={0.88} />
              <stop offset="50%" stopColor={tier.theme.coreColor} stopOpacity={1} />
              <stop offset="55%" stopColor={tier.theme.beamColor1} stopOpacity={0.88} />
              <stop offset="75%" stopColor={tier.theme.beamColor2} stopOpacity={0.3} />
              <stop offset="100%" stopColor={tier.theme.beamColor2} stopOpacity={0} />
            </linearGradient>

            <linearGradient id={plasmaSheathId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={tier.theme.beamColor2} stopOpacity={0} />
              <stop offset="30%" stopColor={tier.theme.beamColor2} stopOpacity={0.2} />
              <stop offset="50%" stopColor={tier.theme.beamColor1} stopOpacity={0.5} />
              <stop offset="70%" stopColor={tier.theme.beamColor2} stopOpacity={0.2} />
              <stop offset="100%" stopColor={tier.theme.beamColor2} stopOpacity={0} />
            </linearGradient>

            <filter id={optMicroId} x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="2.5" />
            </filter>
            <filter id={optSubtleId} x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="9" />
            </filter>
            <filter id={optBloomId} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="28" />
            </filter>
          </defs>

          {/* Relativistic Polar Jets */}
          <line
            x1="50"
            y1="50"
            x2="750"
            y2="750"
            stroke={`url(#${plasmaSheathId})`}
            strokeWidth="26"
            strokeLinecap="round"
            filter={`url(#${optBloomId})`}
            opacity={0.4}
          />
          <line
            x1="65"
            y1="65"
            x2="735"
            y2="735"
            stroke={`url(#${coreJetBeamId})`}
            strokeWidth="12"
            strokeLinecap="round"
            filter={`url(#${optSubtleId})`}
            opacity={0.75}
          />
          <line
            x1="120"
            y1="120"
            x2="680"
            y2="680"
            stroke={`url(#${coreJetBeamId})`}
            strokeWidth="2"
            strokeLinecap="round"
            opacity={0.8}
          />

          {/* Core Halo */}
          <ellipse
            cx="400"
            cy="400"
            rx="220"
            ry="220"
            fill={`url(#${singularityId})`}
            filter={`url(#${optBloomId})`}
            opacity={0.45}
          />

          {/* Rotational Toroidal Accretion Disc */}
          <ellipse
            cx="400"
            cy="400"
            rx="145"
            ry="48"
            fill={`url(#${singularityId})`}
            filter={`url(#${optSubtleId})`}
            opacity={0.5}
            transform="rotate(45 400 400)"
          />
          <ellipse
            cx="400"
            cy="400"
            rx="80"
            ry="26"
            fill={`url(#${singularityId})`}
            filter={`url(#${optMicroId})`}
            opacity={0.7}
            transform="rotate(45 400 400)"
          />

          {/* Harmonious Core Center */}
          <ellipse
            cx="400"
            cy="400"
            rx="20"
            ry="7"
            fill={tier.theme.coreColor}
            opacity={0.95}
            transform="rotate(45 400 400)"
          />
          <circle cx="400" cy="400" r="4" fill={tier.theme.coreColor} opacity={1} />
        </svg>
      </div>

      {/* Level / Status Badge */}
      {showBadge && (
        <div
          className={cn(
            'absolute -bottom-1 -right-1 px-1.5 py-0.2 rounded-full text-[8.5px] font-mono font-bold border leading-tight shadow-md flex items-center justify-center',
            tier.theme.badgeBg,
            tier.theme.badgeText
          )}
        >
          {level}
        </div>
      )}
    </div>
  );
};
