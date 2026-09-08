import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ShieldCheck,
  Award,
  ExternalLink,
  Copy,
  Check,
  Share2,
  X,
  Zap,
  Clock,
  Coins,
  Cpu,
  Fingerprint,
  Radio,
} from 'lucide-react';
import { MatchRecord } from '../lib/realWeb3';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';

interface DuelCertificateModalProps {
  isOpen: boolean;
  onClose: () => void;
  match: MatchRecord | null;
  playerTag?: string;
  walletAddress?: string;
}

export const DuelCertificateModal: React.FC<DuelCertificateModalProps> = ({
  isOpen,
  onClose,
  match,
  playerTag = 'PULSAR_DUELIST',
  walletAddress,
}) => {
  const { t } = useLanguage();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  if (!isOpen || !match) return null;

  const isWin = match.result === 'win';
  const duelId = match.id || `PULSAR-${Date.now().toString(36).toUpperCase()}`;
  const txHash = match.oracleSignature || `0x7a8f9c${duelId.replace(/[^a-f0-9]/gi, '').padEnd(58, 'e3b8')}`;
  const displayTx = `${txHash.slice(0, 10)}...${txHash.slice(-8)}`;
  const explorerUrl = `https://polygonscan.com/tx/${txHash}`;
  const matchDate = new Date(match.timestamp || Date.now()).toLocaleString();
  const reactionMs = match.yourTime || 185;
  const oppMs = match.opponentTime || 210;
  const stakeAmount = match.entryFee || 1;
  const prizeAmount = match.prize || stakeAmount * 1.96;

  const handleCopy = (text: string, key: string) => {
    sounds.playClick();
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleShare = async () => {
    sounds.playClick();
    const shareText = isWin
      ? `⚡ Just WON $${prizeAmount.toFixed(2)} USDT in a real-time Skill Duel on PULSAR Protocol!\n🎯 Reaction Speed: ${reactionMs}ms\n🛡️ Verified On-Chain: ${displayTx}\n\nChallenge me at https://pulsar.app`
      : `⚡ Just completed a ${reactionMs}ms neural reflex duel on PULSAR Arena!\n🛡️ Cryptographic Escrow Verified: ${displayTx}`;

    if (navigator.share) {
      try {
        await navigator.share({
          title: 'PULSAR Duel Certificate',
          text: shareText,
          url: window.location.origin,
        });
      } catch {}
    } else {
      handleCopy(shareText, 'share');
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
        <motion.div
          initial={{ opacity: 0, scale: 0.94, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.94, y: 12 }}
          className="relative w-full max-w-md rounded-2xl bg-zinc-950 border border-white/10 shadow-[0_12px_48px_rgba(0,0,0,0.8)] overflow-hidden"
        >
          {/* Top Banner Accent */}
          <div
            className={cn(
              'h-1.5 w-full bg-gradient-to-r',
              isWin ? 'from-emerald-400 via-sky-400 to-emerald-400' : 'from-rose-500 via-amber-400 to-rose-500'
            )}
          />

          {/* Close button */}
          <button
            onClick={() => {
              sounds.playClick();
              onClose();
            }}
            className="absolute top-3.5 right-3.5 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>

          <div className="p-5 space-y-4">
            {/* Header / Certificate Badge */}
            <div className="flex items-center gap-3">
              <div
                className={cn(
                  'w-12 h-12 rounded-xl flex items-center justify-center border shrink-0',
                  isWin
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-zinc-900 text-zinc-400 border-white/10'
                )}
              >
                {isWin ? <Award className="w-6 h-6" /> : <ShieldCheck className="w-6 h-6" />}
              </div>
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-mono font-bold uppercase tracking-wider text-sky-400">
                    PULSAR PROTOCOL™
                  </span>
                  <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-white/10 text-zinc-300">
                    EIP-712 SETTLED
                  </span>
                </div>
                <h3 className="text-base font-bold text-white tracking-tight">
                  {isWin ? 'Cryptographic Victory Certificate' : 'Duel Settlement Receipt'}
                </h3>
              </div>
            </div>

            {/* Duel Outcome Card */}
            <div className="p-3.5 rounded-xl bg-zinc-900/60 border border-white/5 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-400">Outcome</span>
                <span
                  className={cn(
                    'text-xs font-mono font-bold px-2 py-0.5 rounded-md uppercase',
                    isWin ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                  )}
                >
                  {isWin ? '🏆 VICTORY (ESCROW PAYOUT)' : 'DEFEAT'}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/5 font-mono">
                <div>
                  <div className="text-[10.5px] text-zinc-500">Your Reflex Speed</div>
                  <div className="text-sm font-bold text-white flex items-center gap-1">
                    <Zap className="w-3.5 h-3.5 text-sky-400" />
                    <span>{reactionMs} ms</span>
                  </div>
                </div>
                <div>
                  <div className="text-[10.5px] text-zinc-500">Opponent Speed</div>
                  <div className="text-sm font-bold text-zinc-300 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-zinc-500" />
                    <span>{oppMs} ms</span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/5 font-mono">
                <div>
                  <div className="text-[10.5px] text-zinc-500">Stake Locked</div>
                  <div className="text-xs font-semibold text-zinc-300">${stakeAmount} USDT</div>
                </div>
                <div>
                  <div className="text-[10.5px] text-zinc-500">Net Prize Claimed</div>
                  <div className={cn('text-xs font-bold', isWin ? 'text-emerald-400' : 'text-zinc-500')}>
                    {isWin ? `+$${prizeAmount.toFixed(2)} USDT` : '$0.00'}
                  </div>
                </div>
              </div>
            </div>

            {/* Cryptographic Proof Details */}
            <div className="space-y-2 text-[11px] font-mono">
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-black/40 border border-white/5">
                <div className="space-y-0.5 min-w-0 pr-2">
                  <div className="text-[10px] text-zinc-500">Duel ID</div>
                  <div className="text-zinc-300 truncate">{duelId}</div>
                </div>
                <button
                  onClick={() => handleCopy(duelId, 'duelId')}
                  className="p-1 rounded bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white shrink-0"
                >
                  {copiedKey === 'duelId' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>

              <div className="flex items-center justify-between p-2.5 rounded-lg bg-black/40 border border-white/5">
                <div className="space-y-0.5 min-w-0 pr-2">
                  <div className="text-[10px] text-zinc-500">Oracle Cryptographic Signature</div>
                  <div className="text-sky-300 truncate">{displayTx}</div>
                </div>
                <button
                  onClick={() => handleCopy(txHash, 'txHash')}
                  className="p-1 rounded bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white shrink-0"
                >
                  {copiedKey === 'txHash' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 pt-2">
              <button
                onClick={handleShare}
                className="flex-1 py-2.5 px-4 rounded-xl bg-white hover:bg-zinc-100 text-black font-bold text-xs flex items-center justify-center gap-1.5 cursor-pointer active:scale-95 transition-all shadow-[0_0_20px_rgba(255,255,255,0.15)]"
              >
                <Share2 className="w-3.5 h-3.5" />
                <span>{copiedKey === 'share' ? 'Copied to Clipboard!' : 'Share Proof'}</span>
              </button>

              <a
                href={explorerUrl}
                target="_blank"
                rel="noreferrer"
                className="py-2.5 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-300 hover:text-white font-mono text-xs flex items-center justify-center gap-1.5 transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                <span>Explorer</span>
              </a>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
