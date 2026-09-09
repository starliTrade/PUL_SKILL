import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  Zap,
  ShieldCheck,
  Search,
  ChevronRight,
  Users,
  X,
  Swords,
  Radio,
  Wallet,
  Coins,
  AlertCircle,
  UserPlus,
  Sparkles,
  ArrowRight,
} from 'lucide-react';
import { AppHeader } from '../components/AppHeader';
import { ConnectWallet } from '../components/ConnectWallet';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import { FriendChallengeModal } from '../components/FriendChallengeModal';
import { AntiCheat, getRandomOpponent } from '../lib/antiCheat';
import { sounds } from '../lib/sound';
import { usePulsarStore } from '../store/usePulsarStore';
import { realWeb3Manager, MatchRecord } from '../lib/realWeb3';
import { escrowStatus } from '../lib/escrowFlow';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';
import { gameServerConfigured } from '../lib/gameServerClient';

interface LobbyPageProps {
  onNavigate: (path: string, opponent?: string, stake?: number) => void;
  onStartDuelWithOpponent?: (opponentName: string, stake?: number) => void;
}

const STAKE_TIERS = [
  { fee: 1, label: 'Micro Duel', color: '#e2e8f0', tag: 'Micro' },
  { fee: 2, label: 'Novice Arena', color: '#34d399', tag: 'Novice' },
  { fee: 5, label: 'Veteran Clash', color: '#38bdf8', tag: 'Veteran' },
  { fee: 10, label: 'High Roller', color: '#fbbf24', tag: 'High' },
];

export const LobbyPage: React.FC<LobbyPageProps> = ({
  onNavigate,
  onStartDuelWithOpponent,
}) => {
  const { t } = useLanguage();
  const { wallet, stats, refreshBalance, history } = usePulsarStore();
  const [gameMode, setGameMode] = useState<'real' | 'practice'>('real');
  const [selectedStake, setSelectedStake] = useState<number>(1);
  const [isMatchmaking, setIsMatchmaking] = useState(false);
  const [matchedOpponent, setMatchedOpponent] = useState<string | null>(null);
  const [searchStep, setSearchStep] = useState(0);
  const [mounted, setMounted] = useState(false);
  const [showWalletAlert, setShowWalletAlert] = useState(false);
  const [escrowOfflineAlert, setEscrowOfflineAlert] = useState(false);
  const [showFriendModal, setShowFriendModal] = useState(false);
  const [isRefreshingOnChain, setIsRefreshingOnChain] = useState(false);

  const [liveCloudMatches, setLiveCloudMatches] = useState<MatchRecord[]>([]);

  useEffect(() => {
    setMounted(true);

    const unsubMatches = realWeb3Manager.subscribeGlobalMatches((matches) => {
      if (matches && matches.length > 0) {
        setLiveCloudMatches(matches);
      }
    });

    return () => {
      unsubMatches();
    };
  }, []);

  const prize = (selectedStake * 2) * 0.98;

  const handleStartMatchmaking = () => {
    // P1.15/P2.2: real-money mode is honest — it only exists when BOTH the
    // escrow contract AND the game server are actually deployed. No theater.
    if (gameMode === 'real' && !escrowStatus().configured) {
      sounds.playError();
      setEscrowOfflineAlert(true);
      return;
    }

    if (gameMode === 'real' && !gameServerConfigured()) {
      sounds.playError();
      setEscrowOfflineAlert(true);
      return;
    }

    if (gameMode === 'real' && !wallet.connected) {
      sounds.playError();
      setShowWalletAlert(true);
      return;
    }

    if (gameMode === 'real' && stats.balance < selectedStake) {
      sounds.playError();
      setShowWalletAlert(true);
      return;
    }

    // P2.2: staked matches are matched by the authoritative server on the
    // game screen itself (SIWE → queue → commit/reveal). No simulated search
    // animation for real mode — the wait IS the real matchmaking.
    if (gameMode === 'real') {
      sounds.playClick();
      onNavigate('/game/reaction', undefined, selectedStake);
      return;
      }

    sounds.playClick();
    setIsMatchmaking(true);
    setSearchStep(1);

    setTimeout(() => setSearchStep(2), 1000);
    setTimeout(() => setSearchStep(3), 2000);
    setTimeout(() => {
      const oppName = getRandomOpponent();
      setMatchedOpponent(oppName);
      sounds.playMatchFound();

      setTimeout(() => {
        setIsMatchmaking(false);
        if (onStartDuelWithOpponent) {
          onStartDuelWithOpponent(oppName, 0);
        }
        onNavigate('/game/reaction', oppName, 0);
      }, 1500);
    }, 3200);
  };

  const cancelMatchmaking = () => {
    sounds.playClick();
    setIsMatchmaking(false);
    setMatchedOpponent(null);
    setSearchStep(0);
  };

  const handleRefreshLiveBalances = async () => {
    sounds.playClick();
    setIsRefreshingOnChain(true);
    try {
      await refreshBalance();
      sounds.playWin();
    } catch {}
    setIsRefreshingOnChain(false);
  };

  return (
    <div className="min-h-screen bg-black relative overflow-x-hidden text-zinc-100 selection:bg-white/20">
      <PulsarCosmicBackground className="opacity-90" />
      <div className="absolute inset-0 bg-grid opacity-30 pointer-events-none" />

      {/* Top Header */}
      <AppHeader onNavigate={onNavigate} maxWidthClass="max-w-md" />

      <main className="relative z-10 px-4 pt-4 pb-28 max-w-md mx-auto">
        <div className="mb-4">
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 font-medium tracking-tight mb-1">
            <span className="cursor-pointer hover:text-zinc-300" onClick={() => onNavigate('/')}>{t('navHome')}</span>
            <span className="text-zinc-700">/</span>
            <span className="text-zinc-200">{t('navArena')}</span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-xl font-bold text-white tracking-tight shrink-0">{t('lobbyTitle')}</h1>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => {
                  sounds.playClick();
                  setShowFriendModal(true);
                }}
                className="flex items-center gap-1.5 rounded-full bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-sky-400 px-2.5 py-1 text-[11px] font-semibold transition-all cursor-pointer shadow-sm active:scale-95 whitespace-nowrap"
              >
                <UserPlus className="w-3.5 h-3.5 shrink-0" />
                <span className="whitespace-nowrap">{t('challengeFriend')}</span>
              </button>
              <div className="flex items-center gap-1.5 rounded-full bg-zinc-900/60 border border-white/[0.04] px-2 py-1 shrink-0">
                <div className={cn("w-1.5 h-1.5 rounded-full shrink-0", wallet.connected ? "bg-emerald-400" : "bg-zinc-500")} />
                <span className="text-[10px] text-zinc-300 font-mono whitespace-nowrap">
                  {wallet.connected ? t('navConnected') : t('unconnectedPlayer')}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="mb-3.5 p-1 rounded-xl bg-zinc-950/80 border border-white/[0.06] flex items-center gap-1">
          <button
            onClick={() => {
              sounds.playClick();
              setGameMode('real');
            }}
            className={cn(
              "flex-1 py-2 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer",
              gameMode === 'real'
                ? "bg-zinc-800 text-white font-bold border border-white/10 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.02]"
            )}
          >
            <Zap className={cn("w-3.5 h-3.5", gameMode === 'real' ? "text-amber-400 fill-amber-400" : "text-zinc-500")} />
            <span>{t('modeReal')}</span>
          </button>

          <button
            onClick={() => {
              sounds.playClick();
              setGameMode('practice');
            }}
            className={cn(
              "flex-1 py-2 px-2.5 rounded-lg text-[11px] sm:text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer whitespace-nowrap",
              gameMode === 'practice'
                ? "bg-zinc-800 text-white font-bold border border-white/10 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.02]"
            )}
          >
            <ShieldCheck className={cn("w-3.5 h-3.5 shrink-0", gameMode === 'practice' ? "text-emerald-400" : "text-zinc-500")} />
            <span>{t('modePractice')}</span>
          </button>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="linear-card overflow-hidden mb-5 relative"
        >
          <div className="p-4 border-b border-white/[0.03]">
            <div className="flex items-center gap-3">
              <div className={cn(
                "w-10 h-10 rounded-xl border flex items-center justify-center font-bold shadow-inner shrink-0",
                gameMode === 'real'
                  ? "bg-zinc-900/80 border-white/[0.06] text-sky-400"
                  : "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
              )}>
                {gameMode === 'real' ? <Zap className="w-5 h-5" /> : <ShieldCheck className="w-5 h-5" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 flex-nowrap">
                  <h2 className="text-[13px] font-semibold text-white truncate">
                    {gameMode === 'real' ? t('realStakingTitle') : t('practiceArenaTitle')}
                  </h2>
                  <span className={cn(
                    "text-[8.5px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0 whitespace-nowrap",
                    gameMode === 'real'
                      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                      : "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                  )}>
                    {gameMode === 'real' ? t('realStakingBadge') : t('practiceArenaBadge')}
                  </span>
                </div>
                <p className="text-[11px] text-zinc-400 mt-0.5">
                  {gameMode === 'real'
                    ? t('realStakingSub')
                    : t('practiceArenaSub')}
                </p>
              </div>
            </div>
          </div>

          {gameMode === 'real' ? (
            <>
              <div className="p-3 border-b border-white/[0.04] bg-white/[0.01] space-y-2">
                <div className="flex items-center justify-between text-[10.5px]">
                  <span className="font-semibold text-zinc-300">{t('selectWager')}</span>
                  <span className="text-[9.5px] font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded border border-emerald-500/20">
                    {t('platformFee')}
                  </span>
                </div>

                <div className="grid grid-cols-4 gap-1.5">
                  {STAKE_TIERS.map((tier) => {
                    const isSelected = selectedStake === tier.fee;
                    return (
                      <button
                        key={tier.fee}
                        onClick={() => {
                          sounds.playClick();
                          setSelectedStake(tier.fee);
                        }}
                        className={cn(
                          'py-2 px-1 rounded-xl border text-center transition-all cursor-pointer flex flex-col items-center justify-center relative overflow-hidden active:scale-95',
                          isSelected
                            ? 'bg-emerald-500/15 border-emerald-400/60 text-emerald-300 shadow-[0_0_14px_rgba(52,211,153,0.2)] ring-1 ring-emerald-400/40'
                            : 'bg-zinc-900/50 border-white/[0.04] text-zinc-400 hover:border-white/[0.1] hover:text-zinc-200 hover:bg-zinc-900/80'
                        )}
                      >
                        <span className={cn('text-[11.5px] font-bold font-mono', isSelected ? 'text-emerald-300' : 'text-zinc-200')}>
                          ${tier.fee}
                        </span>
                        <span className={cn('text-[8px] font-mono mt-0.5', isSelected ? 'text-emerald-400/90 font-semibold' : 'text-zinc-400')}>
                          {tier.tag}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-3 divide-x divide-white/[0.03] bg-zinc-950/40 py-2 px-1.5 border-b border-white/[0.04] text-center">
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-zinc-400 font-mono">{t('yourStake')}</div>
                  <div className="text-[11.5px] font-bold text-white font-mono mt-0.5">${selectedStake} USDT</div>
                </div>
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-emerald-400/80 font-mono">{t('winnerPool')}</div>
                  <div className="text-[11.5px] font-bold text-emerald-400 font-mono mt-0.5">${prize.toFixed(2)} USDT</div>
                </div>
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-sky-400/80 font-mono">{t('settlement')}</div>
                  <div className="text-[11.5px] font-bold text-sky-300 font-mono mt-0.5">{t('instantP2P')}</div>
                </div>
              </div>

              <div className="px-3 py-1.5 flex items-center justify-between text-[9.5px] bg-white/[0.01]">
                <div className="flex items-center gap-1.5 text-zinc-400">
                  <ShieldCheck className="w-3 h-3 text-emerald-400 shrink-0" />
                  <span>{t('biometricEntropy')}</span>
                </div>
                <span className="text-zinc-500 font-mono">Polygon Mainnet</span>
              </div>
            </>
          ) : (
            <>
              <div className="p-2.5 bg-zinc-950/40 border-b border-white/[0.04] flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-zinc-300 font-medium text-[10.5px]">{t('adaptiveSentinelAi')}</span>
                </div>
                <span className="text-[9px] font-mono text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                  180ms – 260ms
                </span>
              </div>

              <div className="grid grid-cols-3 divide-x divide-white/[0.03] bg-zinc-950/40 py-2 px-1.5 border-b border-white/[0.04] text-center">
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-zinc-400 font-mono">{t('yourStake')}</div>
                  <div className="text-[11.5px] font-bold text-white font-mono mt-0.5">0 USDT</div>
                </div>
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-emerald-400/80 font-mono">{t('potentialPrize')}</div>
                  <div className="text-[11.5px] font-bold text-emerald-400 font-mono mt-0.5">+50 XP</div>
                </div>
                <div className="px-1">
                  <div className="text-[8.5px] uppercase tracking-wider text-sky-400/80 font-mono">{t('settlement')}</div>
                  <div className="text-[11.5px] font-bold text-sky-300 font-mono mt-0.5">{t('bestOfThree')}</div>
                </div>
              </div>

              <div className="px-3 py-1.5 flex items-center justify-between text-[9.5px] bg-white/[0.01]">
                <div className="flex items-center gap-1.5 text-zinc-400">
                  <ShieldCheck className="w-3 h-3 text-emerald-400 shrink-0" />
                  <span>{t('humanLatencyDist')}</span>
                </div>
                <span className="text-emerald-400 font-mono font-medium">{t('zeroRisk')}</span>
              </div>
            </>
          )}

          <div className="p-2.5 bg-zinc-950/80 border-t border-white/[0.06] backdrop-blur-xl">
            <button
              onClick={handleStartMatchmaking}
              className="group relative w-full rounded-xl overflow-hidden p-0.5 transition-all duration-300 active:scale-[0.98] cursor-pointer"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-sky-500/40 via-white/30 to-emerald-500/40 opacity-80 group-hover:opacity-100 transition-opacity blur-[1px]" />
              <div className="relative rounded-[9px] bg-zinc-950/90 px-3.5 py-2.5 flex items-center justify-between transition-all group-hover:bg-zinc-900/90">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-white/[0.06] border border-white/10 flex items-center justify-center text-white shrink-0 group-hover:scale-105 transition-transform">
                    {gameMode === 'real' ? <Swords className="w-3.5 h-3.5 text-sky-400" /> : <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />}
                  </div>
                  <div className="text-left">
                    <div className="text-[11.5px] font-bold text-white tracking-tight flex items-center gap-1.5">
                      <span>{gameMode === 'real' ? t('joinDuelBtn', { stake: selectedStake }) : t('startPracticeBtn')}</span>
                    </div>
                    <div className="text-[9.5px] font-mono text-emerald-400 font-semibold flex items-center gap-1 mt-0.5">
                      <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse shrink-0" />
                      <span>{gameMode === 'real' ? t('prizeLabel', { prize: prize.toFixed(2) }) : t('freeSparringLabel')}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1 bg-white text-black font-bold text-[11px] px-2.5 py-1 rounded-lg font-mono shadow-sm group-hover:bg-zinc-100 transition-colors shrink-0">
                  <span>{gameMode === 'real' ? t('enterBtn') : t('playBtn')}</span>
                  <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </div>
            </button>

            {gameMode === 'real' && (
              <button
                onClick={() => {
                  sounds.playClick();
                  setShowFriendModal(true);
                }}
                className="mt-1.5 w-full py-1.5 px-2.5 rounded-lg bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.04] text-[10px] text-zinc-400 hover:text-zinc-200 transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <Search className="w-2.5 h-2.5 text-sky-400" />
                <span>{t('searchPlayerBtn')}</span>
              </button>
            )}
          </div>

        </motion.div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
                {t('liveArenaFeed')}
              </h3>
            </div>
            <div className="flex items-center gap-1 text-[10px] text-zinc-400 font-mono">
              <Users className="w-3 h-3 text-emerald-400" />
              <span>{t('liveFeedLabel')}</span>
            </div>
          </div>

          <div className="linear-card divide-y divide-white/[0.04] overflow-hidden">
            {(() => {
              const allSource = liveCloudMatches.length > 0 ? liveCloudMatches : history;
              // STRICTLY SUPPORT & DISPLAY ONLY REAL USDT STAKED BATTLES (stake > 0)
              const matchesToDisplay = allSource.filter((m: any) => {
                const fee = Number(m.entryFee ?? m.stake ?? 0);
                return fee > 0;
              });

              if (matchesToDisplay.length === 0) {
                return (
                  <div className="px-4 py-5 text-center">
                    <p className="text-[11px] text-zinc-500 font-mono">
                      {t('noLiveDuels')}
                    </p>
                  </div>
                );
              }

              return matchesToDisplay.slice(0, 5).map((match: any) => {
                const isWin = match.result === 'win';
                const opp = match.opponentName || match.opponent || 'Arena Duelist';
                const reactionMs = match.yourTime || match.reactionTime || match.opponentTime || 185;
                const stakeVal = Number(match.entryFee ?? match.stake ?? 1);
                const prizeVal = Number(match.prize || (stakeVal * 1.96));

                const timeAgo = match.timestamp
                  ? (() => {
                      const s = Math.floor((Date.now() - match.timestamp) / 1000);
                      if (s < 60) return `${Math.max(1, s)}s ${t('ago')}`;
                      const m = Math.floor(s / 60);
                      if (m < 60) return `${m}m ${t('ago')}`;
                      return `${Math.floor(m / 60)}h ${t('ago')}`;
                    })()
                  : 'Recent';

                return (
                  <div
                    key={match.id}
                    className={cn(
                      "px-3.5 py-2.5 flex items-center justify-between text-xs transition-colors",
                      isWin ? "bg-emerald-500/5 hover:bg-emerald-500/10" : "hover:bg-zinc-900/40"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <div className={cn(
                        "w-2 h-2 rounded-full shrink-0",
                        isWin ? "bg-emerald-400" : "bg-rose-400"
                      )} />
                      <div>
                        <div className="font-semibold text-white tracking-tight flex items-center gap-1">
                          <span className="truncate max-w-[120px]">{opp}</span>
                          <span className="text-[10px] text-zinc-400 font-mono font-normal">
                            ({reactionMs}ms)
                          </span>
                        </div>
                        <div className="text-[10px] text-zinc-500 font-mono">
                          {timeAgo} · ${stakeVal} USDT
                        </div>
                      </div>
                    </div>

                    <div className="text-right font-mono">
                      <div className={cn(
                        "font-bold text-[11px]",
                        isWin ? "text-emerald-400" : "text-zinc-400"
                      )}>
                        {isWin ? `+$${prizeVal.toFixed(2)}` : `-$${stakeVal}`}
                      </div>
                      <div className="text-[9px] text-zinc-600">
                        Staked
                      </div>
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        </div>
      </main>

      {/* Matchmaking Overlay */}
      {isMatchmaking && mounted && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-xl">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-sm linear-card p-6 text-center relative overflow-hidden"
          >
            <div className="relative w-24 h-24 mx-auto mb-5 flex items-center justify-center">
              <div className="absolute inset-0 rounded-full border border-sky-500/20 animate-ping" />
              <div className="absolute inset-2 rounded-full border border-white/10" />
              <div className="w-12 h-12 rounded-2xl bg-zinc-950 border border-white/10 flex items-center justify-center text-sky-400 shadow-xl">
                <Swords className="w-6 h-6 animate-pulse" />
              </div>
            </div>

            <h3 className="text-base font-bold text-white mb-1">
              {matchedOpponent ? t('opponentSecured') : t('searchingDuelists')}
            </h3>
            
            <p className="text-xs text-zinc-400 font-mono mb-6">
              {matchedOpponent 
                ? t('lockingEscrowAgainst', { opponent: matchedOpponent })
                : searchStep === 1 
                  ? t('connectingWs')
                  : searchStep === 2
                    ? t('verifyingAntiCheat')
                    : t('matchingReflexTier')}
            </p>

            {!matchedOpponent && (
              <button
                onClick={cancelMatchmaking}
                className="w-full py-2.5 rounded-xl border border-white/10 text-xs font-semibold text-zinc-400 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
              >
                {t('cancelSearch')}
              </button>
            )}
          </motion.div>
        </div>,
        document.body
      )}

      {/* Insufficient Funds / Connect Wallet Alert Modal */}
      {escrowOfflineAlert && mounted && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-xl">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-sm linear-card p-5 relative"
          >
            <button
              onClick={() => setEscrowOfflineAlert(false)}
              className="absolute top-3 right-3 text-zinc-400 hover:text-white cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 mx-auto mb-3">
              <AlertCircle className="w-5 h-5" />
            </div>

            <h3 className="text-sm font-bold text-white text-center mb-1">{t('escrowOfflineTitle')}</h3>
            <p className="text-xs text-zinc-400 text-center mb-4 leading-relaxed">{t('escrowOfflineDesc')}</p>

            <button
              onClick={() => {
                setEscrowOfflineAlert(false);
                setGameMode('practice');
              }}
              className="w-full py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs font-semibold text-zinc-200 hover:text-white cursor-pointer"
            >
              {t('practiceArenaTitle')}
            </button>
          </motion.div>
        </div>,
        document.body
      )}

      {showWalletAlert && mounted && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/90 backdrop-blur-xl">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-sm linear-card p-5 relative"
          >
            <button
              onClick={() => setShowWalletAlert(false)}
              className="absolute top-3 right-3 text-zinc-400 hover:text-white cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 mx-auto mb-3">
              <AlertCircle className="w-5 h-5" />
            </div>

            <h3 className="text-sm font-bold text-white text-center mb-1">
              {!wallet.connected ? t('navConnect') : t('insufficientBalance')}
            </h3>
            <p className="text-xs text-zinc-400 text-center mb-4 leading-relaxed">
              {!wallet.connected
                ? t('walletSyncHint')
                : t('insufficientBalanceDesc', { stake: selectedStake })}
            </p>

            <div className="space-y-2">
              {!wallet.connected ? (
                <div className="w-full">
                  <ConnectWallet />
                </div>
              ) : (
                <button
                  disabled={isRefreshingOnChain}
                  onClick={handleRefreshLiveBalances}
                  className="w-full py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-black text-xs font-bold transition-colors flex items-center justify-center gap-1.5 cursor-pointer shadow-lg shadow-emerald-500/20"
                >
                  <Coins className={cn('w-4 h-4', isRefreshingOnChain && 'animate-spin')} />
                  <span>{isRefreshingOnChain ? 'Checking Chain...' : t('deposit100Btn')}</span>
                </button>
              )}
              
              <button
                onClick={() => {
                  setShowWalletAlert(false);
                  setGameMode('practice');
                }}
                className="w-full py-2.5 rounded-xl border border-white/10 text-xs font-semibold text-zinc-300 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
              >
                {t('playFreeTrainingMode')}
              </button>
            </div>
          </motion.div>
        </div>,
        document.body
      )}

      {/* Friend Challenge Modal */}
      {showFriendModal && (
        <FriendChallengeModal
          isOpen={showFriendModal}
          selectedStake={selectedStake}
          onClose={() => setShowFriendModal(false)}
          onStartDuel={(oppName, stake) => {
            setShowFriendModal(false);
            if (onStartDuelWithOpponent) {
              onStartDuelWithOpponent(oppName, stake);
            }
            onNavigate('/game/reaction', oppName, stake);
          }}
        />
      )}
    </div>
  );
};
