import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  Sparkles,
  ShieldCheck,
  Zap,
  Activity,
  Layers,
  Coins,
  Copy,
  Check,
  Lock,
  ArrowRight,
  ChevronRight,
  Swords,
  Radio,
  Sliders,
  Flame,
  Terminal,
  Cpu,
  Fingerprint,
} from 'lucide-react';
import { PulsarLogo } from './PulsarLogo';
import { cn } from '../lib/utils';
import { sounds } from '../lib/sound';

interface DesignSystemSampleProps {
  onClose?: () => void;
}

export const DesignSystemSample: React.FC<DesignSystemSampleProps> = ({ onClose }) => {
  const [activeTier, setActiveTier] = useState<number>(2);
  const [toggleActive, setToggleActive] = useState<boolean>(true);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);

  const copyCode = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedSnippet(id);
    setTimeout(() => setCopiedSnippet(null), 2000);
  };

  const TIERS = [
    { fee: 1, prize: 1.96, label: 'Micro Duel' },
    { fee: 2, prize: 3.92, label: 'Novice Arena' },
    { fee: 5, prize: 9.8, label: 'Veteran Clash' },
    { fee: 10, prize: 19.6, label: 'High Roller' },
  ];

  return (
    <div className="min-h-screen bg-black text-zinc-100 p-4 sm:p-8 font-sans selection:bg-white/20">
      <div className="max-w-4xl mx-auto space-y-10">
        
        {/* Header and Archetype Identity */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-white/[0.06]">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[10px] font-mono uppercase tracking-widest text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                Design Archetype
              </span>
              <span className="text-xs text-zinc-500 font-mono">PULSAR UI KIT v1.0</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Linear Dark Minimalist & Cosmic FinTech
            </h1>
            <p className="text-xs sm:text-sm text-zinc-400 mt-1 max-w-xl leading-relaxed">
              الهام‌گرفته از هویت بصری استانداردهای مدرن سیلیکون‌ولی مانند Linear.app، Polar.sh و Vercel با پایه‌ی مشکی عمیق (#000000)، حاشیه‌های میکرونی تک‌پیکسلی (Subtle Borders) و تایپوگرافی با کنتراست بالای مونو و سنس‌سریف.
            </p>
          </div>

          {onClose && (
            <button
              onClick={onClose}
              className="self-start sm:self-auto px-4 py-2 text-xs font-semibold rounded-xl bg-zinc-900 border border-white/[0.08] hover:bg-zinc-800 text-zinc-200 transition-colors cursor-pointer"
            >
              Back to App
            </button>
          )}
        </div>

        {/* 1. Color Palette Tokens */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-400" />
              <span>01. Core Color & Surface Palette</span>
            </h2>
            <span className="text-[10px] font-mono text-zinc-500">Tokens</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3.5 rounded-xl bg-black border border-white/[0.08] space-y-2">
              <div className="h-10 rounded-lg bg-black border border-white/[0.12] flex items-center justify-center text-[10px] font-mono text-zinc-500">
                #000000 (Pure Pitch)
              </div>
              <div>
                <div className="text-xs font-semibold text-white">Base Obsidian</div>
                <div className="text-[10px] text-zinc-500 font-mono">bg-black</div>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-950 border border-white/[0.08] space-y-2">
              <div className="h-10 rounded-lg bg-zinc-900/80 border border-white/[0.04] flex items-center justify-center text-[10px] font-mono text-zinc-400">
                Surface Level 1
              </div>
              <div>
                <div className="text-xs font-semibold text-white">Elevated Card</div>
                <div className="text-[10px] text-zinc-500 font-mono">bg-zinc-950 / linear-card</div>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-950 border border-white/[0.08] space-y-2">
              <div className="h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-[10px] font-mono text-emerald-400 font-bold">
                Emerald Neon (#10B981)
              </div>
              <div>
                <div className="text-xs font-semibold text-white">Verified / Profit</div>
                <div className="text-[10px] text-zinc-500 font-mono">text-emerald-400</div>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-950 border border-white/[0.08] space-y-2">
              <div className="h-10 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-[10px] font-mono text-sky-400 font-bold">
                Cosmic Sky (#38BDF8)
              </div>
              <div>
                <div className="text-xs font-semibold text-white">Oracle / Protocol</div>
                <div className="text-[10px] text-zinc-500 font-mono">text-sky-400</div>
              </div>
            </div>
          </div>
        </section>

        {/* 2. Interactive Stake Tier Chips (1, 2, 5, 10 USDT) */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span>02. Multi-Tier Stake Selector (1$, 2$, 5$, 10$)</span>
            </h2>
            <span className="text-[10px] font-mono text-emerald-400">Live Interactive</span>
          </div>

          <div className="p-5 rounded-2xl bg-zinc-950 border border-white/[0.08] space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold text-white">Select Match Entry Tier</div>
                <p className="text-[11px] text-zinc-400">Instant matchmaking based on chosen stake pool</p>
              </div>
              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-zinc-500">Prize Payout (98%)</span>
                <div className="text-sm font-bold font-mono text-emerald-400">
                  ${TIERS.find((t) => t.fee === activeTier)?.prize.toFixed(2)} USDT
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {TIERS.map((tier) => {
                const isSelected = activeTier === tier.fee;
                return (
                  <button
                    key={tier.fee}
                    onClick={() => {
                      sounds.playClick();
                      setActiveTier(tier.fee);
                    }}
                    className={cn(
                      'p-3 rounded-xl border text-left transition-all cursor-pointer relative overflow-hidden',
                      isSelected
                        ? 'bg-white/[0.06] border-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.15)] ring-1 ring-emerald-400/40'
                        : 'bg-zinc-900/40 border-white/[0.04] hover:border-white/[0.1] hover:bg-zinc-900/80'
                    )}
                  >
                    {isSelected && (
                      <span className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    )}
                    <div className="text-[10px] font-mono text-zinc-400">{tier.label}</div>
                    <div className="text-lg font-extrabold font-mono text-white mt-0.5 flex items-baseline gap-1">
                      <span>{tier.fee}</span>
                      <span className="text-[10px] font-normal text-zinc-400">USDT</span>
                    </div>
                    <div className="text-[10px] font-mono text-emerald-400 mt-1">
                      Win: ${tier.prize}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        {/* 3. High-Contrast Interactive Buttons */}
        <section className="space-y-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            <span>03. Primary & Tactical Button Components</span>
          </h2>

          <div className="p-5 rounded-2xl bg-zinc-950 border border-white/[0.08] grid grid-cols-1 sm:grid-cols-3 gap-4 items-center">
            {/* Solid White High-Contrast Linear Button */}
            <div className="space-y-1.5">
              <button
                onClick={() => sounds.playClick()}
                className="w-full bg-white text-black font-semibold text-xs py-3 px-4 rounded-xl transition-all hover:bg-zinc-200 active:scale-[0.98] flex items-center justify-center gap-2 cursor-pointer shadow-lg"
              >
                <Swords className="w-3.5 h-3.5 fill-black" />
                <span>Join {activeTier} USDT Match</span>
              </button>
              <div className="text-[10px] text-center font-mono text-zinc-500">btn-solid-primary</div>
            </div>

            {/* Ghost Glass Card Button */}
            <div className="space-y-1.5">
              <button
                onClick={() => sounds.playClick()}
                className="w-full bg-zinc-900 border border-white/[0.08] hover:border-white/[0.2] text-zinc-200 hover:text-white font-medium text-xs py-3 px-4 rounded-xl transition-all active:scale-[0.98] flex items-center justify-center gap-2 cursor-pointer"
              >
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Verify Biometrics</span>
              </button>
              <div className="text-[10px] text-center font-mono text-zinc-500">btn-glass-secondary</div>
            </div>

            {/* Glow Neon Micro Button */}
            <div className="space-y-1.5">
              <button
                onClick={() => sounds.playWin()}
                className="w-full bg-emerald-500/10 border border-emerald-500/30 hover:border-emerald-400/60 text-emerald-300 font-semibold text-xs py-3 px-4 rounded-xl transition-all active:scale-[0.98] flex items-center justify-center gap-2 cursor-pointer shadow-[0_0_15px_rgba(16,185,129,0.1)]"
              >
                <Zap className="w-3.5 h-3.5 text-emerald-400" />
                <span>Instant Payout (98%)</span>
              </button>
              <div className="text-[10px] text-center font-mono text-zinc-500">btn-neon-action</div>
            </div>
          </div>
        </section>

        {/* 4. Telemetry Badges & Monospace Data Cells */}
        <section className="space-y-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-400" />
            <span>04. Data Display & Biometric Telemetry Pills</span>
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-4 rounded-xl bg-zinc-950 border border-white/[0.06] space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1.5">
                  <Fingerprint className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Human Kinematic Score</span>
                </span>
                <span className="font-mono font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                  98.4% Verified
                </span>
              </div>
              <p className="text-[11px] text-zinc-500 leading-relaxed">
                Evaluates Fitts's acceleration bell curve and 2-8 Hz hand tremor frequency.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-zinc-950 border border-white/[0.06] space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-zinc-400 flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-sky-400" />
                  <span>EIP-712 Settlement Nonce</span>
                </span>
                <span className="font-mono font-bold text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20">
                  #10842-VALID
                </span>
              </div>
              <p className="text-[11px] text-zinc-500 leading-relaxed">
                Deterministic hash signed by Anti-Cheat Oracle for instant smart contract execution.
              </p>
            </div>
          </div>
        </section>

        {/* 5. Pulsar Stellar Brand Mark & Icon Variants (iOS / Linear / Vercel Luxury Standard) */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-400 font-mono flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-400" />
              <span>05. Pulsar Stellar Mark & Icon Geometry</span>
            </h2>
            <span className="text-[10px] font-mono text-sky-400">Astroid G² Curvature</span>
          </div>

          <div className="p-5 rounded-2xl bg-zinc-950 border border-white/[0.08] space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Glass Squircle (App Icon / Header) */}
              <div className="p-4 rounded-xl bg-black/60 border border-white/[0.06] flex flex-col items-center justify-center text-center space-y-3">
                <PulsarLogo size="lg" variant="glass" showMark={true} />
                <div>
                  <div className="text-xs font-semibold text-white">Glass Obsidian Squircle</div>
                  <div className="text-[10px] text-zinc-500 font-mono">App Icon & Navigation Header</div>
                </div>
              </div>

              {/* Luminous Core Flare (Hero / Splash) */}
              <div className="p-4 rounded-xl bg-black/60 border border-white/[0.06] flex flex-col items-center justify-center text-center space-y-3">
                <PulsarLogo size="lg" variant="luminous" showMark={true} />
                <div>
                  <div className="text-xs font-semibold text-white">Luminous Relativistic Flare</div>
                  <div className="text-[10px] text-zinc-500 font-mono">Hero Splash & Winner Reveal</div>
                </div>
              </div>

              {/* Token Badge (Coin / Treasury) */}
              <div className="p-4 rounded-xl bg-black/60 border border-white/[0.06] flex flex-col items-center justify-center text-center space-y-3">
                <PulsarLogo size="lg" variant="token" showMark={true} />
                <div>
                  <div className="text-xs font-semibold text-white">$PULSAR Token Coin</div>
                  <div className="text-[10px] text-zinc-500 font-mono">DeFi Treasury & Reward Badges</div>
                </div>
              </div>
            </div>

            {/* Size Scale */}
            <div className="pt-4 border-t border-white/[0.06] flex flex-wrap items-center justify-between gap-4">
              <div className="text-[11px] font-mono text-zinc-400">Scale Precision:</div>
              <div className="flex items-center gap-6">
                <PulsarLogo size="xs" showMark={true} />
                <PulsarLogo size="sm" showMark={true} />
                <PulsarLogo size="md" showMark={true} />
                <PulsarLogo size="lg" showMark={true} />
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
};
