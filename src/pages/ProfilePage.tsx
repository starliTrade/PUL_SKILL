import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Wallet,
  Shield,
  ShieldCheck,
  Activity,
  Award,
  Zap,
  TrendingUp,
  Flame,
  Clock,
  ChevronRight,
  ExternalLink,
  Sparkles,
  Lock,
  Layers,
  Copy,
  Check,
  Cpu,
  Radio,
  Sliders,
  Trophy,
  Edit2,
  X,
  Loader2,
} from 'lucide-react';
import { AppHeader } from '../components/AppHeader';
import { ConnectWallet } from '../components/ConnectWallet';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import {
  PulsarDynamicAvatar,
  getAvatarTier,
  AVATAR_STAGES,
} from '../components/PulsarDynamicAvatar';
import { DuelCertificateModal } from '../components/DuelCertificateModal';
import { usePulsarStore } from '../store/usePulsarStore';
import { XPSystem, TierInfo } from '../lib/xpSystem';
import { MatchRecord } from '../lib/realWeb3';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';
import { TranslationKey } from '../i18n/translations';

interface ProfilePageProps {
  onNavigate: (path: string) => void;
}

export const ProfilePage: React.FC<ProfilePageProps> = ({ onNavigate }) => {
  const { t } = useLanguage();
  const {
    wallet,
    stats,
    history,
    bestReactionMs,
    avgReactionMs,
    updatePlayerTag,
  } = usePulsarStore();

  const [copiedAddr, setCopiedAddr] = useState(false);
  const [copiedPlayerId, setCopiedPlayerId] = useState(false);
  const [selectedMatchForCert, setSelectedMatchForCert] = useState<MatchRecord | null>(null);
  const [depositMsg, setDepositMsg] = useState<string | null>(null);
  const [isEditingTag, setIsEditingTag] = useState(false);
  const [isSavingTag, setIsSavingTag] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [tagError, setTagError] = useState<string | null>(null);

  const winRate =
    stats.totalMatches > 0 ? Math.round((stats.wins / stats.totalMatches) * 100) : 0;

  const currentTier = getAvatarTier(stats.level);
  const tierInfo = XPSystem.getTier(stats.level);
  const progressPercent = XPSystem.getLevelProgress(stats.xp);
  const { inLevel, span } = XPSystem.getXPToNextLevel(stats.xp);

  // Financial calculations
  const totalWinnings = history
    .filter((m) => m.result === 'win')
    .reduce((acc, m) => acc + (m.prize - m.entryFee), 0);

  const handleCopyAddress = () => {
    if (wallet.address) {
      sounds.playClick();
      navigator.clipboard.writeText(wallet.address);
      setCopiedAddr(true);
      setTimeout(() => setCopiedAddr(false), 2000);
    }
  };

  const handleCopyPlayerId = () => {
    if (wallet.playerId) {
      sounds.playClick();
      navigator.clipboard.writeText(wallet.playerId);
      setCopiedPlayerId(true);
      setTimeout(() => setCopiedPlayerId(false), 2000);
    }
  };

  const handleStartEditTag = () => {
    sounds.playClick();
    setTagInput(wallet.playerId || '');
    setTagError(null);
    setIsEditingTag(true);
  };

  const handleSaveTag = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = tagInput.trim();
    if (clean.length < 3) {
      setTagError('Username must be at least 3 characters');
      sounds.playLoss();
      return;
    }
    if (clean.length > 20) {
      setTagError('Username cannot exceed 20 characters');
      sounds.playLoss();
      return;
    }
    const pattern = /^[a-zA-Z0-9_]+$/;
    if (!pattern.test(clean)) {
      setTagError('Only English letters, numbers, and (_) allowed');
      sounds.playLoss();
      return;
    }

    try {
      setIsSavingTag(true);
      setTagError(null);
      const res = await updatePlayerTag(clean);
      if (!res.success) {
        setTagError(res.error || 'Username is already taken by another player');
        sounds.playLoss();
      } else {
        sounds.playWin();
        setIsEditingTag(false);
        setDepositMsg(`Username successfully claimed: ${clean}`);
        setTimeout(() => setDepositMsg(null), 3500);
      }
    } catch (err: any) {
      setTagError(err?.message || 'Failed to verify username uniqueness');
    } finally {
      setIsSavingTag(false);
    }
  };

  const PROTOCOL_SPECS = [
    {
      icon: Cpu,
      title: t('antiCheatHardwareTitle'),
      desc: t('antiCheatHardwareDesc'),
      status: t('antiCheatHardwareStatus'),
      statusColor: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    },
    {
      icon: Radio,
      title: t('settlementEscrowTitle'),
      desc: t('settlementEscrowDesc'),
      status: t('settlementEscrowStatus'),
      statusColor: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
    },
    {
      icon: Sliders,
      title: t('latencyBenchmarkTitle'),
      desc: t('latencyBenchmarkDesc'),
      status: avgReactionMs > 0 ? `${avgReactionMs}ms` : t('playDuelHint'),
      statusColor: 'text-zinc-300 bg-white/[0.04] border-white/[0.06]',
    },
  ];

  const getTierTranslationKey = (tierName: string): TranslationKey => {
    if (tierName.includes('Novice')) return 'tierNovice';
    if (tierName.includes('Veteran')) return 'tierVeteran';
    if (tierName.includes('Master')) return 'tierMaster';
    if (tierName.includes('Apex')) return 'tierApex';
    return 'tierGrandmaster';
  };

  const STAGE_I18N_MAP: Record<number, { nameKey: TranslationKey; colorKey: TranslationKey; descKey: TranslationKey }> = {
    1: { nameKey: 'tierNovice', colorKey: 'tierPlatinumWhite', descKey: 'tierNoviceDesc' },
    11: { nameKey: 'tierVeteran', colorKey: 'tierEmerald', descKey: 'tierVeteranDesc' },
    26: { nameKey: 'tierMaster', colorKey: 'tierSolarGold', descKey: 'tierMasterDesc' },
    50: { nameKey: 'tierApex', colorKey: 'tierElectricBlue', descKey: 'tierApexDesc' },
    75: { nameKey: 'tierGrandmaster', colorKey: 'tierHyperViolet', descKey: 'tierGrandmasterDesc' },
  };

  return (
    <div className="min-h-screen bg-black relative overflow-x-hidden text-zinc-100 selection:bg-white/20">
      {/* Dynamic Cosmic Background */}
      <PulsarCosmicBackground className="opacity-70" />
      <div className="absolute inset-0 bg-grid opacity-30 pointer-events-none" />

      {/* Top Header */}
      <AppHeader onNavigate={onNavigate} maxWidthClass="max-w-lg" />

      {/* Main Container */}
      <main className="relative z-10 px-4 pt-4 pb-28 max-w-lg mx-auto space-y-3.5">
        {/* Navigation Breadcrumb */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 font-medium tracking-tight">
            <span className="hover:text-zinc-300 cursor-pointer" onClick={() => onNavigate('/')}>
              {t('navHome')}
            </span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-300">{t('navProfile')}</span>
          </div>
          <span className="text-[10px] text-sky-400/90 font-mono flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
            SIWE Session
          </span>
        </div>

        {/* Master Hero Card: Streamlined Linear Dark Surface with Smart Reactive Border */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-4 rounded-xl linear-card relative overflow-hidden"
        >
          {/* Subtle Ambient Radial Backlight in Tier Color */}
          <div
            className="absolute top-0 left-0 w-32 h-32 rounded-full blur-2xl opacity-10 pointer-events-none transition-colors duration-700"
            style={{ backgroundColor: currentTier.theme.coreColor }}
          />

          {/* Top Row: Refined Compact Avatar & Profile Metadata */}
          <div className="relative z-10 flex items-center gap-3.5">
            {/* Dynamic Avatar with Pulsar Star in User Tier Color */}
            <div className="shrink-0">
              <PulsarDynamicAvatar level={stats.level} size="md" glow showBadge />
            </div>

            {/* Identity, Tags & Wallet Address */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                {isEditingTag ? (
                  <div className="flex-1 min-w-0">
                    <form onSubmit={handleSaveTag} className="flex items-center gap-1 min-w-0" dir="ltr">
                      <input
                        type="text"
                        value={tagInput}
                        disabled={isSavingTag}
                        onChange={(e) => {
                          setTagInput(e.target.value);
                          if (tagError) setTagError(null);
                        }}
                        placeholder="e.g. StarWarrior_7"
                        maxLength={20}
                        autoFocus
                        className="bg-black/90 border border-sky-500/50 rounded px-2 py-0.5 text-xs text-white font-mono focus:outline-none focus:border-sky-400 min-w-0 flex-1 disabled:opacity-50"
                      />
                      <button
                        type="submit"
                        disabled={isSavingTag}
                        className="p-1 rounded bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-black font-bold text-[10px] shrink-0 cursor-pointer flex items-center justify-center min-w-[24px] min-h-[24px]"
                        title="Claim Unique Username"
                      >
                        {isSavingTag ? (
                          <Loader2 className="w-3 h-3 animate-spin text-black" />
                        ) : (
                          <Check className="w-3 h-3" />
                        )}
                      </button>
                      <button
                        type="button"
                        disabled={isSavingTag}
                        onClick={() => setIsEditingTag(false)}
                        className="p-1 rounded bg-white/[0.08] hover:bg-white/[0.15] disabled:opacity-50 text-zinc-300 text-[10px] shrink-0 cursor-pointer min-w-[24px] min-h-[24px] flex items-center justify-center"
                        title="Cancel"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </form>
                    {tagError ? (
                      <span className="text-[9.5px] text-rose-400 block mt-0.5 font-medium">{tagError}</span>
                    ) : (
                      <span className="text-[9px] text-zinc-500 block mt-0.5">3-20 characters • Letters, numbers & (_)</span>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 min-w-0" dir="ltr">
                    <h2
                      data-user-badge="true"
                      className="user-tag-protect text-sm font-bold text-white tracking-tight truncate font-mono"
                      style={{
                        fontFamily: "'JetBrains Mono', 'Plus Jakarta Sans', monospace",
                        direction: 'ltr',
                      }}
                    >
                      {wallet.connected ? (wallet.playerId || 'Pulsar Duelist') : t('unconnectedPlayer')}
                    </h2>
                    {wallet.connected && (
                      <>
                        <button
                          onClick={handleStartEditTag}
                          className="p-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-all cursor-pointer shrink-0"
                          title="Edit Gamer Tag"
                        >
                          <Edit2 className="w-2.5 h-2.5" />
                        </button>
                        {wallet.playerId && (
                          <button
                            onClick={handleCopyPlayerId}
                            className="p-0.5 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-all cursor-pointer shrink-0"
                            title="Copy Player ID"
                          >
                            {copiedPlayerId ? (
                              <Check className="w-2.5 h-2.5 text-emerald-400" />
                            ) : (
                              <Copy className="w-2.5 h-2.5" />
                            )}
                          </button>
                        )}
                      </>
                    )}
                  </div>
                )}

                {/* Tier Badge */}
                <span
                  className={cn(
                    'text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border shrink-0',
                    currentTier.theme.badgeBg,
                    currentTier.theme.badgeText
                  )}
                >
                  {t(getTierTranslationKey(currentTier.name))}
                </span>
              </div>

              {/* Wallet EVM Address or Connect CTA */}
              <div className="mt-1.5 flex items-center justify-between gap-2">
                {wallet.connected && wallet.address ? (
                  <button
                    onClick={handleCopyAddress}
                    dir="ltr"
                    className="group inline-flex items-center gap-1 text-[10.5px] text-zinc-400 hover:text-zinc-200 font-mono bg-white/[0.02] hover:bg-white/[0.05] px-1.5 py-0.5 rounded border border-white/[0.04] hover:border-white/10 transition-colors cursor-pointer shrink-0"
                  >
                    <span className="text-emerald-400 font-medium">EVM:</span>
                    <span>
                      {wallet.address.slice(0, 6)}...{wallet.address.slice(-4)}
                    </span>
                    {copiedAddr ? (
                      <Check className="w-2 h-2 text-emerald-400" />
                    ) : (
                      <Copy className="w-2 h-2 opacity-50 group-hover:opacity-100" />
                    )}
                  </button>
                ) : (
                  <span className="text-[10.5px] text-zinc-500 font-medium flex items-center gap-1 truncate">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400/80 shrink-0" />
                    <span className="truncate">{t('walletSyncHint')}</span>
                  </span>
                )}

                <div className="text-[10.5px] text-zinc-400 font-mono shrink-0">
                  {t('levelLabel')}{' '}
                  <span className="text-white font-medium inline-block" dir="ltr">
                    {stats.level}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Seamless Integrated Progression Module */}
          <div className="mt-3.5 pt-3 border-t border-white/[0.04] relative z-10">
            {/* Upper Info Row */}
            <div className="flex items-center justify-between text-xs mb-1.5">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-[10.5px] font-medium text-zinc-300 flex items-center gap-1 shrink-0">
                  <Sparkles className="w-3 h-3 text-sky-400" />
                  <span>{t('xpMiningProgress')}</span>
                </span>
                <span className="text-[8.5px] font-mono text-zinc-300 bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06] shrink-0 inline-flex items-center">
                  {t('toLevel', { percent: progressPercent, level: stats.level + 1 })}
                </span>
              </div>

              <div className="flex items-center gap-1.5 shrink-0">
                <span className="text-[10.5px] font-mono text-zinc-300" dir="ltr">
                  {inLevel.toLocaleString()} / {span.toLocaleString()}{' '}
                  <span className="text-zinc-500">XP</span>
                </span>

              </div>
            </div>

            {/* Seamless Fluid Progress Bar */}
            <div className="w-full bg-zinc-950 rounded-full h-1 p-0 border border-white/[0.03] overflow-hidden">
              <div
                style={{
                  width: `${progressPercent}%`,
                  backgroundColor: currentTier.theme.coreColor,
                }}
                className="h-full rounded-full transition-all duration-500 shadow-[0_0_6px_rgba(56,189,248,0.4)]"
              />
            </div>

            {/* Micro Mining Yield Metric */}
            <div className="flex items-center justify-between text-[9.5px] text-zinc-500 font-mono mt-1.5">
              <span>{t('multiplierLabel', { multiplier: tierInfo.multiplier })}</span>
              <span className="text-zinc-400 font-medium">{tierInfo.name}</span>
            </div>
          </div>
        </motion.div>

        {/* 4-Stat Mathematical Performance Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div className="linear-card p-2.5 text-center rounded-xl">
            <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
              <Trophy className="w-2.5 h-2.5 text-amber-400" />
              <span>{t('totalMatches')}</span>
            </div>
            <div className="text-base font-bold text-white font-mono" dir="ltr">{stats.totalMatches}</div>
            <div className="text-[9px] text-zinc-500 font-mono" dir="ltr">
              {stats.wins}W - {stats.losses}L
            </div>
          </div>

          <div className="linear-card p-2.5 text-center rounded-xl">
            <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
              <Flame className="w-2.5 h-2.5 text-rose-400" />
              <span>{t('winRate')}</span>
            </div>
            <div className="text-base font-bold text-white font-mono" dir="ltr">{winRate}%</div>
            <div className="text-[9px] text-emerald-400 font-mono">
              <span dir="ltr">{stats.wins}</span> {t('wins')}
            </div>
          </div>

          <div className="linear-card p-2.5 text-center rounded-xl">
            <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
              <Zap className="w-2.5 h-2.5 text-sky-400" />
              <span>{t('bestSpeed')}</span>
            </div>
            <div className="text-base font-bold text-sky-400 font-mono" dir="ltr">
              {bestReactionMs > 0 ? `${bestReactionMs}ms` : '---'}
            </div>
            <div className="text-[9px] text-zinc-500">{t('sub200Target')}</div>
          </div>

          <div className="linear-card p-2.5 text-center rounded-xl">
            <div className="flex items-center justify-center gap-1 text-[9.5px] text-zinc-400 uppercase tracking-wider mb-0.5">
              <Award className="w-2.5 h-2.5 text-purple-400" />
              <span>{t('xpMiningProgress')}</span>
            </div>
            <div className="text-base font-bold text-purple-300 font-mono" dir="ltr">{stats.xp}</div>
            <div className="text-[9px] text-purple-400/80 font-mono">{t('miningActive')}</div>
          </div>
        </div>

        {/* Pulsar Avatar Evolution Matrix (5 Stages Color Breakdown) */}
        <div className="linear-card p-3.5 rounded-xl">
          <div className="flex items-center justify-between mb-2.5">
            <div>
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-300 flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-sky-400" />
                <span>{t('avatarEvolutionTitle')}</span>
              </div>
              <div className="text-[11px] text-zinc-500 mt-0.5">
                {t('avatarEvolutionDesc')}
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            {AVATAR_STAGES.map((stage) => {
              const isUnlocked = stats.level >= stage.lvl;
              const isCurrent =
                stats.level >= stage.lvl &&
                (stage.lvl === 75 || (stage.lvl === 50 && stats.level < 75) || (stage.lvl === 26 && stats.level < 50) || (stage.lvl === 11 && stats.level < 26) || (stage.lvl === 1 && stats.level < 11));

              const stageI18n = STAGE_I18N_MAP[stage.lvl];
              const localizedName = stageI18n ? t(stageI18n.nameKey) : stage.name;
              const localizedColor = stageI18n ? t(stageI18n.colorKey) : stage.colorName;
              const localizedDesc = stageI18n ? t(stageI18n.descKey) : stage.description;

              return (
                <div
                  key={stage.lvl}
                  className={cn(
                    'p-2 rounded-lg border transition-all flex items-center justify-between gap-2.5',
                    isCurrent
                      ? 'bg-white/[0.05] border-white/20 shadow-sm'
                      : isUnlocked
                      ? 'bg-zinc-950/40 border-white/[0.04]'
                      : 'bg-zinc-950/20 border-white/[0.02] opacity-40'
                  )}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="shrink-0">
                      <PulsarDynamicAvatar level={stage.lvl} size="xs" glow={isCurrent} showBadge={false} />
                    </div>

                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-nowrap">
                        <span className="text-xs font-semibold text-white truncate">
                          {localizedName}
                        </span>
                        {isCurrent && (
                          <span className="text-[8px] font-bold uppercase bg-sky-500/20 text-sky-300 px-1 py-0.2 rounded border border-sky-400/30 shrink-0">
                            {t('currentStatus')}
                          </span>
                        )}
                      </div>
                      <div className="text-[10px] text-zinc-500 truncate">
                        {localizedColor} · {localizedDesc}
                      </div>
                    </div>
                  </div>

                  <div className="text-right shrink-0 font-mono">
                    <span className="text-[10.5px] text-zinc-400 font-medium">
                      {t('levelLabel')}{' '}
                      <span dir="ltr" className="inline-block">
                        {stage.lvl}+
                      </span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Cryptographically Settled Duels & Certificates */}
        <div className="linear-card p-3.5 rounded-xl">
          <div className="flex items-center justify-between mb-2.5">
            <div className="flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-sky-400" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
                Settled Battles & Certificates
              </h3>
            </div>
            <span className="text-[9px] font-mono text-zinc-500">
              Click to view on-chain proof
            </span>
          </div>

          {history && history.filter((m: any) => (m.entryFee || m.stake || 0) > 0).length > 0 ? (
            <div className="space-y-1.5">
              {history
                .filter((m: any) => (m.entryFee || m.stake || 0) > 0)
                .slice(0, 4)
                .map((m: any, idx: number) => {
                  const isWin = m.result === 'win';
                  const opp = m.opponentName || m.opponent || 'Duelist';
                  const fee = Number(m.entryFee ?? m.stake ?? 1);
                  const prize = Number(m.prize || fee * 1.96);
                  const timeMs = m.yourTime || m.reactionTime || 185;

                  return (
                    <div
                      key={m.id || idx}
                      onClick={() => {
                        sounds.playClick();
                        setSelectedMatchForCert(m);
                      }}
                      className="p-2.5 rounded-lg bg-zinc-950/40 hover:bg-zinc-900/60 border border-white/[0.04] hover:border-white/10 flex items-center justify-between gap-2 cursor-pointer transition-colors"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className={cn(
                            'w-2 h-2 rounded-full shrink-0',
                            isWin ? 'bg-emerald-400' : 'bg-rose-400'
                          )}
                        />
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-white truncate flex items-center gap-1.5">
                            <span className="truncate">{opp}</span>
                            <span className="text-[10px] font-mono font-normal text-zinc-400">
                              ({timeMs}ms)
                            </span>
                          </div>
                          <div className="text-[10px] font-mono text-zinc-500">
                            ${fee} USDT Stake · {m.oracleSignature ? 'Oracle Verified' : 'Local Result'}
                          </div>
                        </div>
                      </div>

                      <div className="text-right shrink-0 font-mono">
                        <div
                          className={cn(
                            'text-xs font-bold',
                            isWin ? 'text-emerald-400' : 'text-zinc-500'
                          )}
                        >
                          {isWin ? `+$${prize.toFixed(2)}` : `-$${fee}`}
                        </div>
                        <div className="text-[9px] text-sky-400 hover:underline">
                          View Proof →
                        </div>
                      </div>
                    </div>
                  );
                })}
            </div>
          ) : (
            <div className="py-4 text-center text-zinc-500 text-[11px] font-mono">
              No settled USDT duels yet. Win a duel in the arena to generate cryptographic certificates!
            </div>
          )}
        </div>

        {/* Security & Smart Contract Architecture Section */}
        <div className="linear-card p-3.5 rounded-xl">
          <div className="flex items-center gap-1.5 mb-2.5">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
              {t('cryptoSecurityTitle')}
            </h3>
          </div>

          <div className="space-y-2">
            {PROTOCOL_SPECS.map((spec, i) => {
              const Icon = spec.icon;
              return (
                <div
                  key={i}
                  className="p-2 rounded-lg bg-zinc-950/40 border border-white/[0.03] flex items-start gap-2.5"
                >
                  <div className="w-6 h-6 rounded-md bg-white/[0.03] border border-white/[0.06] flex items-center justify-center text-zinc-300 shrink-0 mt-0.5">
                    <Icon className="w-3.5 h-3.5 text-sky-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-semibold text-white tracking-tight truncate">
                        {spec.title}
                      </span>
                      <span
                        className={cn(
                          'text-[8.5px] font-mono px-1.5 py-0.2 rounded border shrink-0',
                          spec.statusColor
                        )}
                      >
                        {spec.status}
                      </span>
                    </div>
                    <p className="text-[10.5px] text-zinc-400 mt-0.5 leading-snug">
                      {spec.desc}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* P2.3 — Legal Center links */}
        <div className="linear-card p-3.5 rounded-xl">
          <div className="flex items-center gap-1.5 mb-2.5">
            <Shield className="w-3.5 h-3.5 text-zinc-400" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
              {t('legalTitle')}
            </h3>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/legal');
              }}
              className="p-2 rounded-lg bg-zinc-950/40 border border-white/[0.04] hover:border-white/10 text-[10.5px] text-zinc-300 hover:text-white transition-colors cursor-pointer text-center"
            >
              {t('legalTosTitle')}
            </button>
            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/legal');
              }}
              className="p-2 rounded-lg bg-zinc-950/40 border border-white/[0.04] hover:border-white/10 text-[10.5px] text-zinc-300 hover:text-white transition-colors cursor-pointer text-center"
            >
              {t('legalPrivacyTitle')}
            </button>
            <button
              onClick={() => {
                sounds.playClick();
                onNavigate('/legal');
              }}
              className="p-2 rounded-lg bg-zinc-950/40 border border-white/[0.04] hover:border-white/10 text-[10.5px] text-amber-400/90 hover:text-amber-300 transition-colors cursor-pointer text-center"
            >
              {t('legalRiskTitle')}
            </button>
          </div>
          <p className="text-[9px] text-zinc-500 mt-2 leading-relaxed">{t('legalEntityNotice')}</p>
        </div>
      </main>


      {/* Duel Cryptographic Certificate Modal */}
      {selectedMatchForCert && (
        <DuelCertificateModal
          isOpen={!!selectedMatchForCert}
          onClose={() => setSelectedMatchForCert(null)}
          match={selectedMatchForCert}
          playerTag={wallet.playerId}
          walletAddress={wallet.address || undefined}
        />
      )}
    </div>
  );
};
