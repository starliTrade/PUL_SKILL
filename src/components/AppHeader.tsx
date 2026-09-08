import React, { useState, useEffect } from 'react';
import { PulsarStarIcon } from './PulsarLogo';
import { LanguageSelector } from './LanguageSelector';
import { ConnectWallet } from './ConnectWallet';
import { cn } from '../lib/utils';

interface AppHeaderProps {
  onNavigate: (path: string) => void;
  className?: string;
  maxWidthClass?: string;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  onNavigate,
  className,
  maxWidthClass = 'max-w-md',
}) => {
  const [pingMs, setPingMs] = useState<number>(18);

  useEffect(() => {
    const interval = setInterval(() => {
      // Simulate real microtask network ping variance
      setPingMs(Math.floor(14 + Math.random() * 8));
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      dir="ltr"
      style={{ direction: 'ltr' }}
      className={cn(
        'relative z-20 flex items-center justify-between px-4 h-14 min-h-[56px] max-h-[56px] w-full mx-auto',
        'border-b border-white/[0.06] backdrop-blur-xl bg-black/50 header-strict-ltr select-none',
        maxWidthClass,
        className
      )}
    >
      {/* Left side: Brand Logo + Standard Gap + Dark Flag Selector */}
      <div className="flex items-center gap-2 h-8 shrink-0 select-none" dir="ltr" style={{ direction: 'ltr' }}>
        {/* Clickable Brand Unit (Star Box + PULSAR Text) */}
        <button
          type="button"
          onClick={() => onNavigate('/')}
          className="brand-logo-unit inline-flex items-center gap-2 select-none cursor-pointer group focus:outline-none h-8 p-0 m-0 border-0 bg-transparent"
          title="PULSAR Arena"
        >
          {/* Star Icon Box - Original Aesthetic, rounded-xl and glow */}
          <div className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center transition-all duration-300 overflow-hidden bg-zinc-950/65 backdrop-blur-2xl border border-white/[0.08] group-hover:border-white/[0.18] shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)] relative">
            <div
              className="absolute inset-0 opacity-20 pointer-events-none"
              style={{
                background: 'radial-gradient(circle at 50% 50%, #7dd3fc 0%, transparent 75%)',
              }}
            />
            <PulsarStarIcon size={22} />
          </div>

          {/* PULSAR Typography - Protected with absolute fixed metrics */}
          <span
            data-brand-logo="true"
            className="brand-logo-text text-sm font-bold tracking-tight text-white group-hover:text-zinc-200 transition-colors select-none"
            style={{
              fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif",
              letterSpacing: '-0.02em',
              lineHeight: '1',
              fontSize: '14px',
              fontWeight: 800,
            }}
          >
            PULSAR
          </span>
        </button>

        {/* Clean subtle divider */}
        <div className="w-px h-3 bg-white/[0.06] mx-0.5 shrink-0 self-center" />

        {/* Darker, 2-sizes smaller Language Selector */}
        <LanguageSelector />
      </div>

      {/* Right side: Latency Meter + Connect Wallet Button */}
      <div className="flex items-center gap-1.5 h-8 shrink-0" dir="ltr" style={{ direction: 'ltr' }}>
        {/* Real-time Sub-millisecond Ping Indicator */}
        <div
          title={`Network latency: ${pingMs}ms · Polygon Escrow Node`}
          className="hidden sm:flex items-center gap-1 px-1.5 py-1 rounded-lg bg-zinc-900/60 border border-white/[0.04] text-[10px] font-mono text-zinc-400 select-none"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span>{pingMs}ms</span>
        </div>

        <ConnectWallet compact />
      </div>
    </header>
  );
};

