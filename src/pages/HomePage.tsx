import React from 'react';
import { motion } from 'motion/react';
import { Sparkles, ArrowRight, Shield, Zap, Trophy, ShieldCheck, Play } from 'lucide-react';
import { AppHeader } from '../components/AppHeader';
import { HeroOrb } from '../components/HeroOrb';
import { HeroTextCosmicBackdrop } from '../components/HeroTextCosmicBackdrop';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import { sounds } from '../lib/sound';
import { useLanguage } from '../i18n/LanguageContext';

interface HomePageProps {
  onNavigate: (path: string, opponent?: string, stake?: number) => void;
}

export const HomePage: React.FC<HomePageProps> = ({ onNavigate }) => {
  const { t } = useLanguage();

  return (
    <div className="min-h-screen bg-black relative overflow-x-hidden text-zinc-100 selection:bg-white/20">
      {/* Ultra-faint celestial starfield & Pulsar star */}
      <PulsarCosmicBackground className="opacity-90" />

      {/* Subtle background grid */}
      <div className="absolute inset-0 bg-grid opacity-30 pointer-events-none" />

      {/* Top Header with Pulsar Brand & Language Selector & Wallet */}
      <AppHeader onNavigate={onNavigate} maxWidthClass="max-w-md" />

      {/* Main Hero Container */}
      <main className="relative z-10 px-4 pt-1 pb-28 max-w-md mx-auto">
        {/* Modern Radar Arena Visualizer */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="relative w-full flex items-center justify-center my-1"
        >
          <HeroOrb className="w-full" onStartBattle={() => onNavigate('/lobby')} />
        </motion.div>

        {/* Hero Section: Headings, Value Proposition & Main CTA with dedicated Cosmic Starfield */}
        <div className="relative my-3 px-3 py-6 rounded-3xl overflow-hidden">
          {/* Faint twinkling stars, subtle pulsar nebula & pulsating radio rings */}
          <HeroTextCosmicBackdrop className="opacity-95" />

          {/* Headings and Value Proposition */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 }}
            className="text-center relative z-10"
          >
            <div className="badge-pill mb-3">
              <Sparkles className="w-3 h-3 text-sky-400" />
              <span className="text-[11px] text-zinc-300 font-medium tracking-tight">
                {t('heroBadge')}
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-white leading-tight tracking-tight">
              <span className="block whitespace-nowrap overflow-hidden text-ellipsis">{t('heroTitleLine1')}</span>
              <span className="block text-zinc-400 font-normal text-xl sm:text-2xl md:text-3xl mt-1 whitespace-nowrap overflow-hidden text-ellipsis">{t('heroTitleLine2')}</span>
            </h1>

            <p className="text-xs text-zinc-400 mt-2.5 max-w-xs mx-auto leading-relaxed">
              {t('heroSubtitle')}
            </p>
          </motion.div>

          {/* Action Buttons */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className="mt-5 flex flex-col items-center gap-2.5 relative z-10"
          >
            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/lobby');
              }}
              className="w-full max-w-xs py-3 px-5 rounded-xl bg-white text-black font-bold text-xs flex items-center justify-center gap-2 transition-all duration-200 hover:bg-zinc-100 active:scale-[0.98] cursor-pointer shadow-[0_0_24px_rgba(255,255,255,0.15)] select-none"
            >
              <Play className="w-3.5 h-3.5 fill-black" />
              <span>{t('heroEnterArena')} ($USDT)</span>
            </button>

            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/game/reaction', 'Practice Sentinel', 0);
              }}
              className="w-full max-w-xs py-2.5 px-4 rounded-xl bg-zinc-950/80 hover:bg-zinc-900 border border-white/[0.12] hover:border-sky-500/40 text-zinc-200 hover:text-white font-medium text-xs flex items-center justify-between transition-all duration-200 shadow-[0_4px_20px_rgba(0,0,0,0.5)] active:scale-[0.98] cursor-pointer select-none group/practice backdrop-blur-xl"
            >
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-sky-500/10 border border-sky-500/25 flex items-center justify-center text-sky-400 group-hover/practice:scale-105 group-hover/practice:bg-sky-500/20 transition-all">
                  <Sparkles className="w-3.5 h-3.5" />
                </div>
                <span className="font-semibold text-zinc-200 group-hover/practice:text-white transition-colors">{t('heroPractice')}</span>
              </div>
              <span className="text-[10px] font-mono text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded-md border border-sky-500/20 group-hover/practice:border-sky-500/40 transition-colors">
                {t('freeTrainingBadge')}
              </span>
            </button>

            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/lobby');
              }}
              className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors flex items-center gap-1.5 cursor-pointer py-1 font-medium group"
            >
              <span>{t('lobbySubtitle')}</span>
              <ArrowRight className="w-3 h-3 text-zinc-400 group-hover:translate-x-0.5 group-hover:text-zinc-200 transition-all rtl:rotate-180" />
            </button>
          </motion.div>
        </div>

        {/* 3 Core Trust Badges - Full complete text, equal heights, balanced responsive layout */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.35 }}
          className="mt-5 grid grid-cols-3 gap-2 sm:gap-2.5 items-stretch"
        >
          {[
            {
              icon: Shield,
              label: t('card1Title'),
              desc: t('card1Sub'),
              color: 'text-emerald-400',
              bg: 'bg-emerald-500/10 border-emerald-500/20',
            },
            {
              icon: Zap,
              label: t('card2Title'),
              desc: t('card2Sub'),
              color: 'text-sky-400',
              bg: 'bg-sky-500/10 border-sky-500/20',
            },
            {
              icon: Trophy,
              label: t('card3Title'),
              desc: t('card3Sub'),
              color: 'text-amber-400',
              bg: 'bg-amber-500/10 border-amber-500/20',
            },
          ].map((item, idx) => (
            <div
              key={idx}
              className="linear-card p-2 sm:p-2.5 text-center rounded-xl transition-colors hover:border-white/[0.1] flex flex-col items-center justify-between h-full min-h-[114px]"
            >
              <div className={`w-7 h-7 rounded-lg ${item.bg} border flex items-center justify-center mx-auto mb-1.5 shrink-0`}>
                <item.icon className={`w-3.5 h-3.5 ${item.color}`} />
              </div>
              <div className="w-full flex-1 flex flex-col justify-center">
                <div className="text-[10.5px] sm:text-[11px] font-bold text-white tracking-tight leading-snug">
                  {item.label}
                </div>
                <div className="text-[9px] sm:text-[9.5px] text-zinc-400 font-normal leading-tight mt-1 opacity-90">
                  {item.desc}
                </div>
              </div>
            </div>
          ))}
        </motion.div>

        {/* Protocol Steps Card */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.45 }}
          className="mt-4 linear-card rounded-xl overflow-hidden"
        >
          <div className="px-3.5 py-2.5 bg-zinc-950/60 border-b border-white/[0.04] flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-zinc-400 font-mono font-semibold">
              {t('smartContract')}
            </span>
            <div className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono font-medium">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>{t('oracleVerified')}</span>
            </div>
          </div>

          <div className="divide-y divide-white/[0.03]">
            {[
              {
                step: '01',
                title: t('feat2Title'),
                desc: t('feat2Desc'),
              },
              {
                step: '02',
                title: t('feat1Title'),
                desc: t('feat1Desc'),
              },
              {
                step: '03',
                title: t('feat3Title'),
                desc: t('feat3Desc'),
              },
            ].map((s) => (
              <div key={s.step} className="p-3 flex items-start gap-3 hover:bg-white/[0.02] transition-colors">
                <span className="text-[10px] font-mono font-bold text-sky-400 mt-0.5 px-2 py-0.5 rounded bg-sky-500/10 border border-sky-500/20 shrink-0">
                  {s.step}
                </span>
                <div>
                  <h4 className="text-xs font-semibold text-white tracking-tight">{s.title}</h4>
                  <p className="text-[10.5px] text-zinc-400 mt-0.5 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* Live Match Activity Bar */}
        <div className="mt-3.5 flex items-center justify-between px-3.5 py-2.5 rounded-xl linear-card text-[11px] hover:border-white/[0.1] transition-colors">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-zinc-400 font-mono text-[10px]">{t('liveFeed')}</span>
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[11px]">
            <span className="text-zinc-300">PulseHunter</span>
            <span className="text-emerald-400 font-bold">+$1.90 USDT</span>
          </div>
        </div>
      </main>
    </div>
  );
};
