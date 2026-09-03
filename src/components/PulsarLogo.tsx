import React from 'react';
import { cn } from '../lib/utils';
import { LanguageSelector } from './LanguageSelector';

interface PulsarLogoProps {
  className?: string;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  showMark?: boolean;
  showLanguageSelector?: boolean;
  variant?: 'minimal' | 'glass' | 'luminous' | 'token';
  onClick?: () => void;
}

const textSizeMap = {
  xs: 'text-xs tracking-wider font-bold',
  sm: 'text-sm font-bold tracking-tight',
  md: 'text-base font-bold tracking-tight',
  lg: 'text-xl font-extrabold tracking-tight',
  xl: 'text-3xl font-black tracking-tight',
};

const sizeConfig = {
  xs: { box: 'w-6 h-6 rounded-lg', star: 16 },
  sm: { box: 'w-8 h-8 rounded-xl', star: 22 },
  md: { box: 'w-10 h-10 rounded-xl', star: 28 },
  lg: { box: 'w-12 h-12 rounded-xl', star: 34 },
  xl: { box: 'w-16 h-16 rounded-2xl', star: 46 },
};

/**
 * Astrophysical Pulsar Star Icon - Signature Electric Sky Blue Edition
 */
export const PulsarStarIcon: React.FC<{
  className?: string;
  size?: number;
  glow?: boolean;
  showFlare?: boolean;
}> = ({ className, size = 22 }) => {
  const rawId = React.useId();
  const id = rawId.replace(/[^a-zA-Z0-9]/g, '');
  const singularityId = `pulsar-sing-${id}`;
  const coreJetBeamId = `pulsar-jet-${id}`;
  const plasmaSheathId = `pulsar-sheath-${id}`;
  const optMicroId = `pulsar-micro-${id}`;
  const optSubtleId = `pulsar-subtle-${id}`;
  const optBloomId = `pulsar-bloom-${id}`;

  const coreColor = '#e0f2fe';
  const beamColor1 = '#7dd3fc';
  const beamColor2 = '#0284c7';

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 800 800"
      width={size}
      height={size}
      className={cn('shrink-0 overflow-visible relative z-10 select-none', className)}
    >
      <defs>
        <radialGradient id={singularityId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={coreColor} stopOpacity={1} />
          <stop offset="10%" stopColor={beamColor1} stopOpacity={0.8} />
          <stop offset="35%" stopColor={beamColor2} stopOpacity={0.4} />
          <stop offset="70%" stopColor="#000000" stopOpacity={0.05} />
          <stop offset="100%" stopColor="#000000" stopOpacity={0} />
        </radialGradient>

        <linearGradient id={coreJetBeamId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={beamColor2} stopOpacity={0} />
          <stop offset="25%" stopColor={beamColor2} stopOpacity={0.3} />
          <stop offset="45%" stopColor={beamColor1} stopOpacity={0.85} />
          <stop offset="50%" stopColor={coreColor} stopOpacity={0.98} />
          <stop offset="55%" stopColor={beamColor1} stopOpacity={0.85} />
          <stop offset="75%" stopColor={beamColor2} stopOpacity={0.3} />
          <stop offset="100%" stopColor={beamColor2} stopOpacity={0} />
        </linearGradient>

        <linearGradient id={plasmaSheathId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={beamColor2} stopOpacity={0} />
          <stop offset="30%" stopColor={beamColor2} stopOpacity={0.2} />
          <stop offset="50%" stopColor={beamColor1} stopOpacity={0.45} />
          <stop offset="70%" stopColor={beamColor2} stopOpacity={0.2} />
          <stop offset="100%" stopColor={beamColor2} stopOpacity={0} />
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
        fill={coreColor}
        opacity={0.9}
        transform="rotate(45 400 400)"
      />
      <circle cx="400" cy="400" r="4" fill={coreColor} opacity={0.95} />
    </svg>
  );
};

export const PulsarLogo: React.FC<PulsarLogoProps> = ({
  className,
  size = 'sm',
  showMark = true,
  showLanguageSelector = false,
  onClick,
}) => {
  const cfg = sizeConfig[size];

  return (
    <div
      onClick={onClick}
      dir="ltr"
      style={{ direction: 'ltr' }}
      className={cn(
        'inline-flex items-center gap-2 select-none cursor-pointer group h-8 shrink-0',
        className
      )}
    >
      {showMark && (
        <div
          className={cn(
            'relative shrink-0 flex items-center justify-center transition-all duration-300 overflow-hidden',
            'bg-zinc-950/65 backdrop-blur-2xl border border-white/[0.08] group-hover:border-white/[0.18]',
            'shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)]',
            sizeConfig[size].box
          )}
        >
          {/* Subtle Ambient Backlight in Signature Sky Blue */}
          <div
            className="absolute inset-0 opacity-20 pointer-events-none"
            style={{
              background: 'radial-gradient(circle at 50% 50%, #7dd3fc 0%, transparent 75%)',
            }}
          />

          {/* Electric Sky Blue Pulsar Star Icon */}
          <PulsarStarIcon size={sizeConfig[size].star} />
        </div>
      )}

      {/* Modern High-End Typography */}
      <span
        data-brand-logo="true"
        style={{
          fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif",
          letterSpacing: '-0.02em',
        }}
        className={cn(
          'text-white tracking-tight font-extrabold transition-colors duration-200 group-hover:text-zinc-200 brand-logo-text leading-none select-none',
          textSizeMap[size]
        )}
      >
        PULSAR
      </span>

      {showLanguageSelector && size !== 'xs' && (
        <div className="inline-flex items-center ml-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          <LanguageSelector />
        </div>
      )}
    </div>
  );
};
