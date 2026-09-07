import React from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  Sparkles,
  X,
  ShieldCheck,
  Zap,
  TrendingUp,
  Layers,
  Award,
  CheckCircle2,
} from 'lucide-react';
import { TOKENOMICS_SPEC, XPSystem, TierInfo } from '../lib/xpSystem';
import { PulsarStarIcon } from './PulsarLogo';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';

interface TokenomicsInspectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  userLevel?: number;
  userXP?: number;
}

export const TokenomicsInspectorModal: React.FC<TokenomicsInspectorModalProps> = ({
  isOpen,
  onClose,
  userLevel = 1,
  userXP = 0,
}) => {
  const { t } = useLanguage();
  if (typeof document === 'undefined') return null;

  const currentTier = XPSystem.getTierInfo(userLevel);
  const estimatedTokens = (userXP * 0.01 * currentTier.multiplier).toFixed(2);

  const ALL_TIERS: TierInfo[] = [
    XPSystem.getTierInfo(1),
    XPSystem.getTierInfo(15),
    XPSystem.getTierInfo(35),
    XPSystem.getTierInfo(55),
  ];

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[999999] flex items-end justify-center sm:items-center">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/85 backdrop-blur-md"
            onClick={onClose}
          />

          {/* Modal Card */}
          <motion.div
            initial={{ y: '100%', opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: '100%', opacity: 0 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            className="relative z-10 w-full max-w-lg px-3 pb-4 sm:p-0"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="linear-card-elevated p-5 w-full space-y-4 max-h-[90vh] overflow-y-auto custom-scrollbar border border-sky-500/20 shadow-[0_8px_36px_rgba(14,165,233,0.12)]">
              {/* Top Handle on Mobile */}
              <div className="w-10 h-1 rounded-full bg-zinc-800 mx-auto sm:hidden" />

              {/* Header */}
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-sky-500/20 to-cyan-500/10 border border-sky-400/30 flex items-center justify-center text-sky-400 shadow-[0_0_14px_rgba(56,189,248,0.25)]">
                    <PulsarStarIcon size={20} glow={false} showFlare={false} />
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-sm font-bold text-white tracking-tight">
                        {TOKENOMICS_SPEC.tokenName}
                      </h3>
                      <span className="text-[10px] font-mono font-bold bg-amber-400/15 text-amber-300 border border-amber-400/25 px-1.5 py-0.5 rounded">
                        {TOKENOMICS_SPEC.tokenTicker}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-400">
                      {t('tokenomicsSub')}
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => {
                    sounds.playClick();
                    onClose();
                  }}
                  className="text-zinc-400 hover:text-white p-1.5 rounded-lg hover:bg-white/[0.04] transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* User Live Claim Power Box */}
              <div className="p-3.5 rounded-xl bg-gradient-to-r from-sky-950/60 via-zinc-900/80 to-zinc-900 border border-sky-500/25 flex items-center justify-between">
                <div>
                  <div className="text-[10px] uppercase font-mono tracking-wider text-sky-300 font-semibold flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-sky-400" />
                    <span>{t('claimPower')}</span>
                  </div>
                  <div className="flex items-baseline gap-2 mt-1">
                    <span className="text-xl font-bold font-mono text-white">
                      ~{estimatedTokens}
                    </span>
                    <span className="text-xs font-mono font-bold text-amber-400">
                      {TOKENOMICS_SPEC.tokenTicker}
                    </span>
                  </div>
                  <div className="text-[10px] text-zinc-400 mt-0.5">
                    {t('basedOnXp', { xp: userXP.toLocaleString(), multiplier: currentTier.multiplier, tier: currentTier.name })}
                  </div>
                </div>

                <div className="text-right">
                  <div className={cn('text-xs font-bold font-mono px-2 py-1 rounded-lg border', currentTier.bgColor, currentTier.borderColor, currentTier.color)}>
                    {currentTier.badge}
                  </div>
                  <div className="text-[9px] font-mono text-zinc-500 mt-1">{t('levelLabel')} {userLevel}</div>
                </div>
              </div>

              {/* Core Token Specs Grid */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-white/[0.04]">
                  <div className="text-[10px] text-zinc-500 font-mono">{t('maxSupply')}</div>
                  <div className="text-xs font-bold text-white font-mono mt-0.5">
                    {TOKENOMICS_SPEC.totalSupply}
                  </div>
                </div>
                <div className="p-2.5 rounded-xl bg-zinc-900/60 border border-white/[0.04]">
                  <div className="text-[10px] text-zinc-500 font-mono">{t('settlementStandard')}</div>
                  <div className="text-xs font-bold text-emerald-400 font-mono mt-0.5">
                    Polygon Mainnet / EIP-712
                  </div>
                </div>
              </div>

              {/* Distribution Allocation */}
              <div className="space-y-2">
                <div className="text-[11px] font-semibold text-zinc-300 flex items-center justify-between">
                  <span>{t('tokenMatrix')}</span>
                  <span className="text-[10px] font-mono text-zinc-500">{t('fixedFair')}</span>
                </div>

                {/* Progress bar split */}
                <div className="w-full h-2 rounded-full overflow-hidden flex bg-zinc-800">
                  {TOKENOMICS_SPEC.distribution.map((item, idx) => (
                    <div
                      key={idx}
                      style={{ width: `${item.percent}%` }}
                      className={cn('h-full', item.color)}
                      title={`${item.label} (${item.percent}%)`}
                    />
                  ))}
                </div>

                <div className="space-y-1.5 pt-1">
                  {TOKENOMICS_SPEC.distribution.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-2">
                        <div className={cn('w-2 h-2 rounded-full', item.color)} />
                        <span className="text-zinc-300">{item.label}</span>
                      </div>
                      <span className="font-mono font-bold text-white">{item.percent}%</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tier Multipliers Breakdown */}
              <div className="space-y-2 pt-2 border-t border-white/[0.04]">
                <div className="text-[11px] font-semibold text-zinc-300 flex items-center gap-1.5">
                  <Award className="w-3.5 h-3.5 text-amber-400" />
                  <span>{t('avatarEvolutionTitle')}</span>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {ALL_TIERS.map((tier) => {
                    const isCurrent = userLevel >= tier.minLevel && userLevel <= tier.maxLevel;
                    return (
                      <div
                        key={tier.badge}
                        className={cn(
                          'p-2.5 rounded-xl border text-left transition-all',
                          isCurrent
                            ? `${tier.bgColor} ${tier.borderColor} ring-1 ring-white/10`
                            : 'bg-zinc-900/40 border-white/[0.04]'
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <span className={cn('text-xs font-bold', tier.color)}>{tier.name}</span>
                          <span className="text-[10px] font-mono font-bold text-white bg-white/[0.08] px-1.5 py-0.5 rounded">
                            {tier.multiplier}x
                          </span>
                        </div>
                        <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                          {t('levelLabel')} {tier.minLevel} - {tier.maxLevel === 999 ? '50+' : tier.maxLevel}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Protocol Utility */}
              <div className="space-y-1.5 pt-2 border-t border-white/[0.04]">
                <div className="text-[11px] font-semibold text-zinc-300 flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" />
                  <span>{t('cryptoSecurityTitle')}</span>
                </div>
                <div className="space-y-1">
                  {TOKENOMICS_SPEC.utilities.map((util, i) => (
                    <div key={i} className="flex items-start gap-2 text-[10px] text-zinc-400 leading-relaxed">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0 mt-0.5" />
                      <span>{util}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Footer CTA */}
              <button
                onClick={() => {
                  sounds.playClick();
                  onClose();
                }}
                className="w-full btn-primary py-2.5 text-xs font-semibold flex items-center justify-center gap-2 cursor-pointer mt-2"
              >
                <span>{t('backToLobby')}</span>
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body
  );
};
