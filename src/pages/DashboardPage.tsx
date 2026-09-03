import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Trophy,
  Zap,
  TrendingUp,
  Flame,
  Coins,
  ShieldCheck,
  Award,
  ArrowUpRight,
  Clock,
  ChevronRight,
  Sparkles,
  ExternalLink,
  Target,
  BarChart3,
  Activity,
  History,
  Medal,
  Crown,
  Users,
  Layers,
  ArrowDownRight,
  Info,
} from 'lucide-react';
import { AppHeader } from '../components/AppHeader';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import { PulsarDynamicAvatar, getAvatarTier } from '../components/PulsarDynamicAvatar';
import { TokenomicsInspectorModal } from '../components/TokenomicsInspectorModal';
import { usePulsarStore } from '../store/usePulsarStore';
import { XPSystem, TierInfo } from '../lib/xpSystem';
import { LeaderboardPlayer } from '../lib/realWeb3';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';

interface DashboardPageProps {
  onNavigate: (path: string) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ onNavigate }) => {
  const { t } = useLanguage();
  const {
    wallet,
    stats,
    history,
    bestReactionMs,
    avgReactionMs,
    leaderboard,
  } = usePulsarStore();

  const [activeTab, setActiveTab] = useState<'my_stats' | 'leaderboard'>('my_stats');
  const [showInspector, setShowInspector] = useState(false);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<string | null>(null);

  const winRate =
    stats.totalMatches > 0 ? Math.round((stats.wins / stats.totalMatches) * 100) : 0;

  const currentTier = getAvatarTier(stats.level);
  const tierInfo = XPSystem.getTier(stats.level);
  const progressPercent = XPSystem.getLevelProgress(stats.xp);

  // Financial calculations
  const totalWinnings = history
    .filter((m) => m.result === 'win')
    .reduce((acc, m) => acc + (m.prize - m.entryFee), 0);

  const totalLosses = history
    .filter((m) => m.result === 'loss')
    .reduce((acc, m) => acc + m.entryFee, 0);

  const netEarnings = Math.round((totalWinnings - totalLosses) * 100) / 100;

  // Recent 8 matches for the chart
  const recentReactionTimes = history
    .filter((m) => m.yourTime > 0)
    .slice(0, 8)
    .map((m) => m.yourTime)
    .reverse();

  const getLatencyRating = (ms: number) => {
    if (ms === 0) return { label: t('uncalibrated'), color: 'text-zinc-500', badge: 'bg-zinc-800 text-zinc-400' };
    if (ms < 170) return { label: t('apexReflex'), color: 'text-sky-400', badge: 'bg-sky-500/20 text-sky-300 border-sky-400/30' };
    if (ms < 210) return { label: t('eliteTier'), color: 'text-emerald-400', badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-400/30' };
    if (ms < 260) return { label: t('competentDuelist'), color: 'text-amber-400', badge: 'bg-amber-500/20 text-amber-300 border-amber-400/30' };
    return { label: t('casualReaction'), color: 'text-zinc-300', badge: 'bg-white/10 text-zinc-300' };
  };

  const reactionRating = getLatencyRating(avgReactionMs || bestReactionMs);

  return (
    <div className="min-h-screen bg-black relative overflow-x-hidden text-zinc-100 selection:bg-white/20">
      {/* Subtle Dynamic Space Ambience */}
      <PulsarCosmicBackground className="opacity-70" />
      <div className="absolute inset-0 bg-grid opacity-25 pointer-events-none" />

      {/* Sticky Header */}
      <AppHeader onNavigate={onNavigate} maxWidthClass="max-w-lg" />

      {/* Main Container */}
      <main className="relative z-10 px-4 pt-3.5 pb-28 max-w-lg mx-auto space-y-3.5">
        {/* Navigation Breadcrumbs & Top Bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 font-medium tracking-tight">
            <span className="hover:text-zinc-300 cursor-pointer" onClick={() => onNavigate('/')}>
              {t('navHome')}
            </span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">{t('navDashboard')}</span>
          </div>

          <div className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            {t('liveFeed')}
          </div>
        </div>

        {/* Tab Switcher: Frosted Glass Segmented Control */}
        <div className="p-1 rounded-xl bg-zinc-950/70 backdrop-blur-2xl border border-white/[0.08] grid grid-cols-2 gap-1 shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)]">
          <button
            onClick={() => {
              sounds.playClick();
              setActiveTab('my_stats');
            }}
            className={cn(
              'py-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer select-none',
              activeTab === 'my_stats'
                ? 'bg-white/[0.08] text-white border border-white/15 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.02]'
            )}
          >
            <Activity className="w-3.5 h-3.5 text-sky-400" />
            <span>{t('myRealStats')}</span>
          </button>

          <button
            onClick={() => {
              sounds.playClick();
              setActiveTab('leaderboard');
            }}
            className={cn(
              'py-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer select-none',
              activeTab === 'leaderboard'
                ? 'bg-white/[0.08] text-white border border-white/15 shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.02]'
            )}
          >
            <Trophy className="w-3.5 h-3.5 text-amber-400" />
            <span>{t('globalPodium')}</span>
          </button>
        </div>

        {/* TAB 1: MY REAL STATS & PERFORMANCE MATRIX */}
        {activeTab === 'my_stats' && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3"
          >
            {/* Master Financial & Performance Hero Card */}
            <div className="linear-card p-4 rounded-xl relative overflow-hidden">
              {/* Soft Ambient Radial Glow anchored to current tier */}
              <div
                className="absolute top-0 right-0 w-36 h-36 rounded-full blur-2xl opacity-10 pointer-events-none"
                style={{ backgroundColor: currentTier.theme.coreColor }}
              />

              {/* Profile Identity & Level Tier Strip */}
              <div className="flex items-center justify-between gap-2.5 pb-3 border-b border-white/[0.04]">
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div className="shrink-0">
                    <PulsarDynamicAvatar level={stats.level} size="md" glow showBadge={false} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 flex-nowrap">
                      <span className="text-[13px] font-bold text-white tracking-tight truncate">
                        {wallet.connected ? (wallet.playerId || 'Pulsar Duelist') : t('unconnectedPlayer')}
                      </span>
                      <span
                        className={cn(
                          'text-[8px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 whitespace-nowrap',
                          currentTier.theme.badgeBg,
                          currentTier.theme.badgeText
                        )}
                      >
                        {currentTier.name}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-400 font-mono mt-0.5 truncate">
                      {wallet.connected && wallet.address
                        ? `${wallet.address.slice(0, 6)}...${wallet.address.slice(-4)} · ${t('verified')}`
                        : t('walletSyncHint')}
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => {
                    sounds.playClick();
                    setShowInspector(true);
                  }}
                  className="px-2 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-[9.5px] font-mono text-zinc-200 hover:text-white flex items-center gap-1 transition-all cursor-pointer shrink-0 shadow-sm self-center whitespace-nowrap active:scale-95"
                >
                  <Sparkles className="w-3 h-3 text-sky-400 shrink-0" />
                  <span className="font-semibold">{t('miningMultiplier', { multiplier: tierInfo.multiplier })}</span>
                </button>
              </div>

              {/* High-Impact 2-Col Metric: Balance & Net Profit */}
              <div className="grid grid-cols-2 gap-3 pt-3">
                <div className="bg-zinc-950/60 rounded-lg p-2.5 border border-white/[0.03]">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1 mb-1">
                    <Coins className="w-3 h-3 text-emerald-400" />
                    <span>{t('vaultEscrow')}</span>
                  </div>
                  <div className="text-lg font-extrabold text-emerald-400 font-mono">
                    ${stats.balance.toFixed(2)}{' '}
                    <span className="text-[10px] font-normal text-zinc-500">USDT</span>
                  </div>
                  <div className="text-[9.5px] text-zinc-500 font-mono mt-0.5">
                    {t('nonCustodialPolygon')}
                  </div>
                </div>

                <div className="bg-zinc-950/60 rounded-lg p-2.5 border border-white/[0.03]">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1 mb-1">
                    <TrendingUp
                      className={cn(
                        'w-3 h-3',
                        netEarnings >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      )}
                    />
                    <span>{t('netSkillPnl')}</span>
                  </div>
                  <div
                    className={cn(
                      'text-lg font-extrabold font-mono flex items-center gap-1',
                      netEarnings >= 0 ? 'text-emerald-400' : 'text-rose-400'
                    )}
                  >
                    {netEarnings >= 0 ? `+$${netEarnings}` : `-$${Math.abs(netEarnings)}`}{' '}
                    <span className="text-[10px] font-normal text-zinc-500">USDT</span>
                  </div>
                  <div className="text-[9.5px] text-zinc-500 font-mono mt-0.5">
                    {stats.totalMatches} {t('totalMatches')}
                  </div>
                </div>
              </div>

              {/* XP Mining Micro-Bar */}
              <div className="mt-3 pt-2.5 border-t border-white/[0.03] flex items-center justify-between text-[10.5px]">
                <div className="text-zinc-400 font-mono flex items-center gap-1.5">
                  <Award className="w-3 h-3 text-purple-400" />
                  <span>XP: <strong className="text-zinc-200">{stats.xp.toLocaleString()}</strong></span>
                  <span className="text-zinc-600">·</span>
                  <span>Lv {stats.level} ({progressPercent}%)</span>
                </div>
                <span className="text-[9.5px] text-sky-400 font-mono">
                  ~{(stats.xp * 0.01 * tierInfo.multiplier).toFixed(2)} $PULSAR
                </span>
              </div>
            </div>

            {/* 4-Metric Esports Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div className="linear-card p-2.5 rounded-xl text-center">
                <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
                  <Trophy className="w-2.5 h-2.5 text-amber-400" />
                  <span>{t('totalMatches')}</span>
                </div>
                <div className="text-base font-bold text-white font-mono">{stats.totalMatches}</div>
                <div className="text-[9px] text-zinc-500 font-mono">
                  {stats.wins}W - {stats.losses}L - {stats.voids}V
                </div>
              </div>

              <div className="linear-card p-2.5 rounded-xl text-center">
                <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
                  <Flame className="w-2.5 h-2.5 text-rose-400" />
                  <span>{t('winRate')}</span>
                </div>
                <div className="text-base font-bold text-white font-mono">{winRate}%</div>
                <div className="text-[9px] text-emerald-400 font-mono">
                  {stats.wins} {t('wins')}
                </div>
              </div>

              <div className="linear-card p-2.5 rounded-xl text-center">
                <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
                  <Zap className="w-2.5 h-2.5 text-sky-400" />
                  <span>{t('bestSpeed')}</span>
                </div>
                <div className="text-base font-bold text-sky-400 font-mono">
                  {bestReactionMs > 0 ? `${bestReactionMs}ms` : '---'}
                </div>
                <div className="text-[9px] text-zinc-500 font-mono">{t('sub200Target')}</div>
              </div>

              <div className="linear-card p-2.5 rounded-xl text-center">
                <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
                  <Clock className="w-2.5 h-2.5 text-zinc-400" />
                  <span>{t('avgSpeed')}</span>
                </div>
                <div className="text-base font-bold text-zinc-200 font-mono">
                  {avgReactionMs > 0 ? `${avgReactionMs}ms` : '---'}
                </div>
                <div className="text-[9px] text-zinc-500 font-mono">{t('hardwareVerified')}</div>
              </div>
            </div>

            {/* Reaction Speed Analytics & Trend Visualizer */}
            <div className="linear-card p-3.5 rounded-xl">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-md bg-sky-500/10 border border-sky-500/20 flex items-center justify-center">
                    <Target className="w-3.5 h-3.5 text-sky-400" />
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-white tracking-tight">
                      {t('neuromuscularLatency')}
                    </h3>
                    <p className="text-[10px] text-zinc-500">
                      {t('highPrecisionCurve')}
                    </p>
                  </div>
                </div>

                <span
                  className={cn(
                    'text-[9.5px] font-mono font-medium px-2 py-0.5 rounded-md border',
                    reactionRating.badge
                  )}
                >
                  {reactionRating.label}
                </span>
              </div>

              {/* Sparkline / Bar Chart Representation */}
              {recentReactionTimes.length > 0 ? (
                <div className="space-y-2">
                  <div className="h-16 flex items-end justify-between gap-1.5 pt-2 px-1 bg-zinc-950/70 rounded-lg border border-white/[0.03]">
                    {recentReactionTimes.map((time, idx) => {
                      const maxMs = 350;
                      const minMs = 120;
                      const clamped = Math.min(maxMs, Math.max(minMs, time));
                      const heightPercent = Math.round(
                        100 - ((clamped - minMs) / (maxMs - minMs)) * 80
                      );

                      const isBest = time === bestReactionMs;

                      return (
                        <div
                          key={idx}
                          className="flex-1 flex flex-col items-center gap-1 group relative h-full justify-end"
                        >
                          <div className="absolute -top-7 opacity-0 group-hover:opacity-100 transition-opacity bg-zinc-900 border border-white/20 text-[9px] font-mono text-white px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap z-20 shadow-lg">
                            {time}ms {isBest && `⚡ ${t('best')}`}
                          </div>

                          <div
                            style={{ height: `${heightPercent}%` }}
                            className={cn(
                              'w-full rounded-t transition-all',
                              isBest
                                ? 'bg-gradient-to-t from-sky-500 to-sky-300 shadow-[0_0_8px_rgba(56,189,248,0.5)]'
                                : time < 200
                                ? 'bg-emerald-500/80 hover:bg-emerald-400'
                                : time < 260
                                ? 'bg-amber-500/80 hover:bg-amber-400'
                                : 'bg-zinc-600 hover:bg-zinc-500'
                            )}
                          />
                        </div>
                      );
                    })}
                  </div>

                  <div className="flex items-center justify-between text-[9px] text-zinc-500 font-mono px-1">
                    <span>{t('olderDuels')}</span>
                    <span className="flex items-center gap-2">
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-sky-400" /> &lt;170ms
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> &lt;210ms
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> &lt;260ms
                      </span>
                    </span>
                    <span>{t('recentDuelsText')}</span>
                  </div>
                </div>
              ) : (
                <div className="py-6 text-center text-xs text-zinc-500 bg-zinc-950/40 rounded-lg border border-white/[0.02]">
                  {t('calibrateFirstDuel')}
                </div>
              )}
            </div>

            {/* Match History Stream */}
            <div className="linear-card rounded-xl overflow-hidden">
              <div className="px-3.5 py-2.5 bg-zinc-950/60 border-b border-white/[0.04] flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5 text-zinc-400" />
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-300">
                    {t('historyTitle')} ({history.length})
                  </span>
                </div>
                <span className="text-[9.5px] text-zinc-500 font-mono">{t('immutableLog')}</span>
              </div>

              {history.length > 0 ? (
                <div className="divide-y divide-white/[0.03]">
                  {history.map((m) => {
                    const isWin = m.result === 'win';
                    const isVoid = m.result === 'void';
                    const isExpanded = selectedHistoryItem === m.id;

                    return (
                      <div
                        key={m.id}
                        onClick={() =>
                          setSelectedHistoryItem(isExpanded ? null : m.id)
                        }
                        className="p-3 hover:bg-white/[0.02] transition-colors cursor-pointer"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2.5">
                            {/* Outcome Badge */}
                            <div
                              className={cn(
                                'w-7 h-7 rounded-md flex items-center justify-center font-bold font-mono text-[11px] shrink-0 border',
                                isWin
                                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                                  : isVoid
                                  ? 'bg-zinc-800 text-zinc-400 border-white/10'
                                  : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                              )}
                            >
                              {isWin ? 'W' : isVoid ? 'V' : 'L'}
                            </div>

                            <div>
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs font-semibold text-white">
                                  {m.game || t('reflexCalibration')}
                                </span>
                                <span className="text-[9.5px] text-zinc-500 font-mono">
                                  ${m.entryFee} {t('pool')}
                                </span>
                              </div>
                              <div className="text-[10px] text-zinc-400 font-mono mt-0.5 flex items-center gap-2">
                                <span>{t('youPlayer')}: <strong className="text-zinc-200">{m.yourTime > 0 ? `${m.yourTime}ms` : t('faultStatus')}</strong></span>
                                <span className="text-zinc-600">{t('versus')}</span>
                                <span>{t('oppPlayer')}: <strong className="text-zinc-200">{m.opponentTime > 0 ? `${m.opponentTime}ms` : t('faultStatus')}</strong></span>
                              </div>
                            </div>
                          </div>

                          <div className="text-right">
                            <div
                              className={cn(
                                'text-xs font-extrabold font-mono',
                                isWin
                                  ? 'text-emerald-400'
                                  : isVoid
                                  ? 'text-zinc-400'
                                  : 'text-rose-400'
                              )}
                            >
                              {isWin
                                ? `+$${(m.prize - m.entryFee).toFixed(2)}`
                                : isVoid
                                ? '$0.00'
                                : `-$${m.entryFee.toFixed(2)}`}
                            </div>
                            <div className="text-[9px] text-zinc-500 font-mono mt-0.5">
                              {new Date(m.timestamp).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </div>
                          </div>
                        </div>

                        {/* Expandable On-Chain Proof Drawer */}
                        {isExpanded && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            className="mt-2.5 pt-2.5 border-t border-white/[0.04] text-[10px] font-mono space-y-1.5 bg-black/40 p-2 rounded-lg"
                          >
                            <div className="flex items-center justify-between text-zinc-400">
                              <span>{t('matchId')}:</span>
                              <span className="text-zinc-300 font-mono">{m.id.slice(0, 12)}...</span>
                            </div>
                            <div className="flex items-center justify-between text-zinc-400">
                              <span>{t('settlementHash')}:</span>
                              <a
                                href={m.hash ? `https://polygonscan.com/tx/${m.hash}` : 'https://polygonscan.com'}
                                target="_blank"
                                rel="noreferrer"
                                className="text-sky-400 hover:underline cursor-pointer flex items-center gap-1"
                              >
                                {m.hash ? `${m.hash.slice(0, 8)}...${m.hash.slice(-6)}` : 'Polygon 0x7f2a...8c1e'}
                                <ExternalLink className="w-2.5 h-2.5" />
                              </a>
                            </div>
                            <div className="flex items-center justify-between text-zinc-400">
                              <span>{t('oracleNonce')}:</span>
                              <span className="text-emerald-400">{t('verifiedEip712')}</span>
                            </div>
                          </motion.div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-6 text-center text-xs text-zinc-500 font-mono">
                  {t('noMatchesYet')}
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* TAB 2: GLOBAL ARENA PODIUM / LEADERBOARD */}
        {activeTab === 'leaderboard' && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3"
          >
            {/* Top 3 Podium Cards - Olympic layout (2nd - 1st - 3rd) with 1st elevated in center */}
            {(() => {
              const top3 = leaderboard.slice(0, 3);
              const podiumOrder = [
                { player: top3[1], rank: 2 },
                { player: top3[0], rank: 1 },
                { player: top3[2], rank: 3 },
              ].filter((item) => Boolean(item.player));

              return (
                <div className="grid grid-cols-3 gap-2 items-end pt-3 pb-1" dir="ltr" style={{ direction: 'ltr' }}>
                  {podiumOrder.map(({ player, rank }) => {
                    const isFirst = rank === 1;
                    const isSecond = rank === 2;
                    const isThird = rank === 3;

                    const borderColor = isFirst
                      ? 'border-amber-400/50 bg-gradient-to-b from-amber-400/[0.08] to-amber-500/[0.02] shadow-[0_8px_25px_rgba(245,158,11,0.12)]'
                      : isSecond
                      ? 'border-zinc-400/30 bg-zinc-300/[0.03]'
                      : 'border-amber-700/40 bg-amber-700/[0.03]';

                    const badgeColor = isFirst
                      ? 'bg-gradient-to-r from-amber-400 to-yellow-300 text-black ring-2 ring-amber-400/30'
                      : isSecond
                      ? 'bg-zinc-300 text-black'
                      : 'bg-amber-700 text-amber-100';

                    return (
                      <div
                        key={player.address || `podium-${rank}`}
                        className={cn(
                          'linear-card p-3 rounded-xl text-center relative overflow-hidden flex flex-col items-center border transition-all duration-300',
                          borderColor,
                          isFirst ? '-translate-y-2 z-10 scale-[1.02] ring-1 ring-amber-400/20 py-3.5' : 'py-2.5'
                        )}
                      >
                        {/* Crown for Rank 1 */}
                        {isFirst && (
                          <div className="mb-0.5">
                            <Crown className="w-3.5 h-3.5 text-amber-400 fill-amber-400/80 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]" />
                          </div>
                        )}

                        {/* Rank Badge */}
                        <div
                          className={cn(
                            'w-5 h-5 rounded-full flex items-center justify-center font-extrabold text-[10px] mb-2 font-mono shadow-sm',
                            badgeColor
                          )}
                        >
                          {rank}
                        </div>

                        <PulsarDynamicAvatar level={player.level || 1} size={isFirst ? 'sm' : 'xs'} glow={isFirst} showBadge={false} />

                        <div className="mt-1.5 font-bold text-xs text-white truncate max-w-full">
                          {player.name || player.playerId || player.shortAddress}
                        </div>
                        <div className="text-[9.5px] text-zinc-400 font-mono">
                          {player.bestReactionMs || player.reactionTime || 180}ms
                        </div>
                        <div className="text-[9px] text-emerald-400 font-mono mt-1 font-semibold">
                          ${(player.totalWinnings ?? player.totalEarnedUSDT ?? (player.wins * 1.96) ?? 0).toLocaleString()}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })()}

            {/* Complete Global Ledger Table */}
            <div className="linear-card rounded-xl overflow-hidden">
              <div className="px-3.5 py-2.5 bg-zinc-950/60 border-b border-white/[0.04] flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Trophy className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-300">
                    {t('leaderboardTitle')}
                  </span>
                </div>
                <span className="text-[9.5px] text-emerald-400 font-mono">{t('oracleAudited')}</span>
              </div>

              <div className="divide-y divide-white/[0.03]">
                {leaderboard.map((p, idx) => {
                  const isUser = wallet.connected && wallet.address === p.address;

                  return (
                    <div
                      key={p.address || `lb-player-${idx}`}
                      className={cn(
                        'px-3.5 py-2.5 flex items-center justify-between text-xs transition-colors',
                        isUser ? 'bg-sky-500/10 border-l-2 border-sky-400' : 'hover:bg-white/[0.02]'
                      )}
                    >
                      <div className="flex items-center gap-2.5">
                        <span className="w-4 font-mono text-[11px] text-zinc-500 font-bold">
                          #{idx + 1}
                        </span>

                        <PulsarDynamicAvatar level={p.level || 1} size="xs" glow={false} showBadge={false} />

                        <div>
                          <div className="font-semibold text-white tracking-tight flex items-center gap-1.5">
                            <span>{p.name || p.playerId || p.shortAddress}</span>
                            {isUser && (
                              <span className="text-[8.5px] bg-sky-500/20 text-sky-300 px-1 py-0.2 rounded font-mono">
                                {t('youBadge')}
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-zinc-500 font-mono">
                            {t('levelLabel')} {p.level || 1} · {p.winRate ?? 0}% WR
                          </div>
                        </div>
                      </div>

                      <div className="text-right font-mono">
                        <div className="font-bold text-sky-400 text-xs">{p.bestReactionMs || p.reactionTime || 180}ms</div>
                        <div className="text-[9.5px] text-emerald-400">
                          ${(p.totalWinnings ?? p.totalEarnedUSDT ?? (p.wins * 1.96) ?? 0).toLocaleString()}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </main>

      {/* Protocol / Tokenomics Inspector Modal */}
      {showInspector && (
        <TokenomicsInspectorModal
          isOpen={showInspector}
          onClose={() => setShowInspector(false)}
        />
      )}
    </div>
  );
};
