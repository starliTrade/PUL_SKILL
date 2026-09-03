import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Wallet,
  Shield,
  Activity,
  Award,
  Zap,
  TrendingUp,
  Flame,
  Clock,
  Coins,
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
  Info,
  Trophy,
} from 'lucide-react';
import { AppHeader } from '../components/AppHeader';
import { ConnectWallet } from '../components/ConnectWallet';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import {
  PulsarDynamicAvatar,
  getAvatarTier,
  AVATAR_STAGES,
} from '../components/PulsarDynamicAvatar';
import { TokenomicsInspectorModal } from '../components/TokenomicsInspectorModal';
import { usePulsarStore } from '../store/usePulsarStore';
import { XPSystem, TierInfo } from '../lib/xpSystem';
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
    depositFunds,
  } = usePulsarStore();

  const [copiedAddr, setCopiedAddr] = useState(false);
  const [copiedPlayerId, setCopiedPlayerId] = useState(false);
  const [showInspector, setShowInspector] = useState(false);
  const [depositMsg, setDepositMsg] = useState<string | null>(null);

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

  const estimatedPulsarTokens = (stats.xp * 0.01 * tierInfo.multiplier).toFixed(
    1
  );

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

  const handleDepositVaultFunds = (amount: number) => {
    sounds.playWin();
    depositFunds(amount);
    setDepositMsg(`+${amount} USDT added to Vault!`);
    setTimeout(() => setDepositMsg(null), 3000);
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
            EIP-712 Active
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
                <div className="flex items-center gap-1.5 min-w-0">
                  <h2 className="text-sm font-semibold text-white tracking-tight truncate">
                    {wallet.connected ? (wallet.playerId || 'Pulsar Duelist') : t('unconnectedPlayer')}
                  </h2>
                  {wallet.connected && wallet.playerId && (
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
                </div>

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

                <button
                  onClick={() => {
                    sounds.playClick();
                    setShowInspector(true);
                  }}
                  title="View $PULSAR Tokenomics & Mining Specs"
                  className="w-4 h-4 rounded bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.06] flex items-center justify-center text-zinc-400 hover:text-white transition-colors cursor-pointer"
                >
                  <Info className="w-2.5 h-2.5" />
                </button>
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
              <span className="text-zinc-400 font-medium">
                {t('estYield', { yield: estimatedPulsarTokens })}
              </span>
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

        {/* Vault Balance & Faucet Topup Section */}
        <div className="linear-card p-3.5 rounded-xl">
          <div className="flex items-center justify-between gap-3 mb-2.5">
            <div className="flex-1 min-w-0 pr-2 rtl:pr-0 rtl:pl-2">
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                <Coins className="w-3 h-3 text-emerald-400 shrink-0" />
                <span className="truncate">{t('vaultEscrow')}</span>
              </div>
              <div className="text-[11px] text-zinc-500 mt-0.5 line-clamp-2 leading-tight">
                {t('directOnchainBalance')}
              </div>
            </div>
            <div className="shrink-0 text-right rtl:text-left">
              <div className="text-base font-bold text-emerald-400 font-mono inline-flex items-center gap-1" dir="ltr">
                <span>${stats.balance.toFixed(2)}</span>
                <span className="text-xs text-emerald-500/80 font-sans">USDT</span>
              </div>
              <div className="text-[9px] text-zinc-500 font-mono mt-0.5">Polygon Mainnet</div>
            </div>
          </div>

          {wallet.connected ? (
            <div className="pt-2 border-t border-white/[0.04]">
              <button
                onClick={() => handleDepositVaultFunds(20)}
                className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold text-emerald-300 transition-all cursor-pointer shadow-sm active:scale-[0.98]"
              >
                <Coins className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="truncate">{t('depositUSDT')} (+20 USDT)</span>
              </button>
            </div>
          ) : (
            <div className="pt-2 border-t border-white/[0.04] flex justify-center">
              <ConnectWallet />
            </div>
          )}

          {depositMsg && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-2 text-center text-[11px] text-emerald-400 font-medium bg-emerald-500/10 border border-emerald-500/20 py-1.5 px-2.5 rounded-lg flex items-center justify-center gap-1.5"
            >
              <Sparkles className="w-3 h-3 text-emerald-400 shrink-0" />
              <span>{depositMsg}</span>
            </motion.div>
          )}
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
      </main>

      {/* Tokenomics Modal */}
      {showInspector && (
        <TokenomicsInspectorModal
          isOpen={showInspector}
          onClose={() => setShowInspector(false)}
        />
      )}
    </div>
  );
};
