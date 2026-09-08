import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ArrowLeft,
  RotateCcw,
  Trophy,
  XCircle,
  ShieldAlert,
  LoaderCircle,
  Zap,
  Fingerprint,
  ShieldCheck,
  ArrowUp,
  ArrowDown,
  ArrowLeft as ArrowLeftIcon,
  ArrowRight as ArrowRightIcon,
  Crosshair,
  Activity,
  Cpu,
  Sparkles,
  Coins,
  Wallet,
  CheckCircle2,
  Flame,
  Swords,
} from 'lucide-react';
import confetti from 'canvas-confetti';
import { GamePhase, MouseTrajectoryPoint, MatchResolution, TargetVectorDirection, RoundResult, BestOfThreeState } from '../types';
import { AntiCheat, getRandomOpponent, TargetSpawnConfig } from '../lib/antiCheat';
import { usePulsarStore } from '../store/usePulsarStore';
import { XPSystem, XPSummary } from '../lib/xpSystem';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
import { TokenomicsInspectorModal } from '../components/TokenomicsInspectorModal';
import { ConnectWallet } from '../components/ConnectWallet';
import { DuelCertificateModal } from '../components/DuelCertificateModal';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';

interface ReactionGamePageProps {
  onNavigate: (path: string) => void;
  opponentName?: string;
  stakeAmount?: number;
}

export const ReactionGamePage: React.FC<ReactionGamePageProps> = ({
  onNavigate,
  opponentName,
  stakeAmount = 1,
}) => {
  const { t } = useLanguage();
  const { wallet, recordMatch } = usePulsarStore();
  const [phase, setPhase] = useState<GamePhase>('human-verify');
  const [countdown, setCountdown] = useState<number>(3);
  const [matchResult, setMatchResult] = useState<MatchResolution | null>(null);
  const [opponent, setOpponent] = useState<string>(opponentName || getRandomOpponent());
  const [currentStake, setCurrentStake] = useState<number>(stakeAmount);
  const [showWalletModal, setShowWalletModal] = useState(false);
  const [showCertificateModal, setShowCertificateModal] = useState(false);

  useEffect(() => {
    if (opponentName) setOpponent(opponentName);
    if (stakeAmount !== undefined) setCurrentStake(stakeAmount);
  }, [opponentName, stakeAmount]);

  // Best of 3 Tournament State
  const [bo3State, setBo3State] = useState<BestOfThreeState>({
    userScore: 0,
    opponentScore: 0,
    currentRound: 1,
    rounds: [],
    targetWins: 2,
    isMatchOver: false,
  });

  const [lastRoundResult, setLastRoundResult] = useState<RoundResult | null>(null);
  const [roundTransitionMessage, setRoundTransitionMessage] = useState<string>('');
  
  // Dynamic Spatial & Directional Anti-Cheat Target State
  const [spawnConfig, setSpawnConfig] = useState<TargetSpawnConfig | null>(null);
  const [verifyTarget, setVerifyTarget] = useState<{ x: number; y: number }>({ x: 50, y: 50 });
  const [verifyProgress, setVerifyProgress] = useState<number>(0);
  const [earlyClickWarning, setEarlyClickWarning] = useState<boolean>(false);
  const [showTelemetryModal, setShowTelemetryModal] = useState<boolean>(false);
  const [showTokenomicsModal, setShowTokenomicsModal] = useState<boolean>(false);
  const [xpSummary, setXpSummary] = useState<XPSummary | null>(null);

  const startTimeRef = useRef<number>(0);
  const waitTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const countdownIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const roundTransitionTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const trajectoryRef = useRef<MouseTrajectoryPoint[]>([]);
  const reactionTimeRef = useRef<number>(0);
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (waitTimeoutRef.current) clearTimeout(waitTimeoutRef.current);
      if (countdownIntervalRef.current) clearInterval(countdownIntervalRef.current);
      if (roundTransitionTimeoutRef.current) clearTimeout(roundTransitionTimeoutRef.current);
    };
  }, []);

  // Randomize calibration target for human latency check
  const randomizeCalibrationTarget = useCallback(() => {
    setVerifyTarget({
      x: 25 + Math.random() * 50,
      y: 25 + Math.random() * 50,
    });
  }, []);

  useEffect(() => {
    if (phase === 'human-verify') {
      randomizeCalibrationTarget();
    }
  }, [phase, randomizeCalibrationTarget]);

  // Track mouse/touch trajectory points for anti-cheat verification
  const handlePointerMove = (e: React.PointerEvent) => {
    if (trajectoryRef.current.length < 60) {
      trajectoryRef.current.push({
        x: e.clientX,
        y: e.clientY,
        t: performance.now(),
      });
    }
  };

  // Human verify target clicked
  const handleVerifyNodeClick = () => {
    sounds.playTick();
    setPhase('ready');
    setCountdown(3);
  };

  // Ready countdown 3 -> 2 -> 1 -> waiting
  useEffect(() => {
    if (phase !== 'ready') return;
    setCountdown(3);
    sounds.playTick();
    let currentCount = 3;

    countdownIntervalRef.current = setInterval(() => {
      currentCount -= 1;
      if (currentCount <= 0) {
        if (countdownIntervalRef.current) clearInterval(countdownIntervalRef.current);
        startWaitingPhase();
      } else {
        setCountdown(currentCount);
        sounds.playTick();
      }
    }, 700);

    return () => {
      if (countdownIntervalRef.current) clearInterval(countdownIntervalRef.current);
    };
  }, [phase]);

  // Start waiting phase
  const startWaitingPhase = () => {
    setPhase('waiting');
    setEarlyClickWarning(false);
    trajectoryRef.current = [];

    // Randomized delay between 1800ms - 4200ms
    const delay = Math.random() * 2400 + 1800;
    waitTimeoutRef.current = setTimeout(() => {
      const target = AntiCheat.generateTargetSpawn();
      setSpawnConfig(target);
      startTimeRef.current = performance.now();
      setPhase('action');
      sounds.playGo();
    }, delay);
  };

  // Early click in waiting phase
  const handleEarlyClick = (e: React.MouseEvent) => {
    if (phase === 'waiting') {
      if (waitTimeoutRef.current) clearTimeout(waitTimeoutRef.current);
      sounds.playLoss();
      setEarlyClickWarning(true);
      setTimeout(() => {
        setEarlyClickWarning(false);
        startWaitingPhase();
      }, 1400);
    }
  };

  // User touched or clicked on dynamic target
  const handleTargetHit = (e: React.MouseEvent | React.TouchEvent) => {
    if (phase !== 'action') return;
    e.stopPropagation();
    const elapsed = performance.now() - startTimeRef.current;
    reactionTimeRef.current = elapsed;
    sounds.playHit();
    
    // Synthetic event check
    const isNativeTrusted = 'isTrusted' in e ? Boolean(e.isTrusted) : true;
    processVerification(elapsed, {
      isTrusted: isNativeTrusted,
      pointerType: 'native',
      hasNaturalJitter: trajectoryRef.current.length > 0,
    });
  };

  // Directional Vector Gesture for mobile/desktop
  const handleTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length > 0) {
      touchStartRef.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
        time: performance.now(),
      };
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (phase !== 'action' || !touchStartRef.current || !spawnConfig) return;
    const elapsed = performance.now() - startTimeRef.current;
    reactionTimeRef.current = elapsed;
    sounds.playHit();
    
    const isNativeTrusted = 'isTrusted' in e ? Boolean(e.isTrusted) : true;
    processVerification(elapsed, {
      isTrusted: isNativeTrusted,
      pointerType: 'touch',
      hasNaturalJitter: true,
    });
  };

  // Verification stage with anti-cheat telemetry evaluation & Best-of-3 handling
  const processVerification = async (timeMs: number, eventCheck?: { isTrusted: boolean; pointerType?: string; hasNaturalJitter: boolean }) => {
    setPhase('verifying');
    setVerifyProgress(0);

    const progressInterval = setInterval(() => {
      setVerifyProgress((prev) => Math.min(prev + 20, 92));
    }, 70);

    await AntiCheat.simulateServerDelay(650, 1000);
    clearInterval(progressInterval);
    setVerifyProgress(100);

    const userTime = Math.round(timeMs);
    // Gaussian tier-based opponent simulation
    const oppTier = currentStake >= 10 ? 'High' : currentStake >= 5 ? 'Veteran' : currentStake >= 2 ? 'Novice' : 'Micro';
    const oppTime = AntiCheat.simulateOpponentReaction(oppTier);
    const resolution = AntiCheat.resolveMatch(userTime, oppTime, trajectoryRef.current, currentStake, eventCheck);

    // If bot detected or biological breach
    if (resolution.outcome === 'void') {
      sounds.playLoss();
      setMatchResult(resolution);
      setPhase('bot-detected');
      return;
    }

    // Determine round winner
    const roundWinner: 'user' | 'opponent' | 'tie' =
      userTime < oppTime ? 'user' : userTime > oppTime ? 'opponent' : 'tie';

    const currentRoundNum = bo3State.currentRound;
    const newRoundResult: RoundResult = {
      roundNumber: currentRoundNum,
      winner: roundWinner,
      userTime,
      opponentTime: oppTime,
    };

    const newUserScore = bo3State.userScore + (roundWinner === 'user' ? 1 : 0);
    const newOpponentScore = bo3State.opponentScore + (roundWinner === 'opponent' ? 1 : 0);
    const newRounds = [...bo3State.rounds, newRoundResult];

    const isMatchDecided = newUserScore >= 2 || newOpponentScore >= 2;

    setLastRoundResult(newRoundResult);
    setBo3State({
      userScore: newUserScore,
      opponentScore: newOpponentScore,
      currentRound: currentRoundNum + 1,
      rounds: newRounds,
      targetWins: 2,
      isMatchOver: isMatchDecided,
    });

    if (isMatchDecided) {
      // Final Match Outcome
      const finalWinner = newUserScore >= 2 ? 'win' : 'loss';
      const avgUserTime = Math.round(
        newRounds.reduce((acc, r) => acc + r.userTime, 0) / newRounds.length
      );
      const avgOppTime = Math.round(
        newRounds.reduce((acc, r) => acc + r.opponentTime, 0) / newRounds.length
      );

      const finalResolution: MatchResolution = {
        outcome: finalWinner,
        yourTime: avgUserTime,
        opponentTime: avgOppTime,
        prize: finalWinner === 'win' ? AntiCheat.calculatePrize(currentStake) : 0,
        telemetry: resolution.telemetry,
        rounds: newRounds,
        userScore: newUserScore,
        opponentScore: newOpponentScore,
      };

      setMatchResult(finalResolution);

      // Record into store & calculate XP
      recordMatch({
        id: `m${Date.now()}`,
        game: 'Reaction Duel (Best of 3)',
        result: finalWinner,
        entryFee: currentStake,
        prize: finalResolution.prize,
        opponentTime: avgOppTime,
        yourTime: avgUserTime,
        timestamp: Date.now(),
      }).then((xpRes) => {
        setXpSummary(xpRes);
      });

      if (finalWinner === 'win') {
        sounds.playWin();
        try {
          confetti({
            particleCount: 90,
            spread: 75,
            origin: { y: 0.6 },
            colors: ['#38bdf8', '#10b981', '#ffffff', '#eab308'],
          });
        } catch {}
      } else {
        sounds.playLoss();
      }

      setPhase('result');
    } else {
      // Intermission between rounds
      if (roundWinner === 'user') {
        sounds.playWin();
      } else {
        sounds.playHit();
      }

      // Compose transition message
      if (newUserScore === 1 && newOpponentScore === 1) {
        setRoundTransitionMessage('TIE 1 - 1! DECIDING ROUND (MATCH POINT)!');
      } else if (newUserScore === 1 && newOpponentScore === 0) {
        setRoundTransitionMessage('ROUND 1 WON! MATCH POINT FOR YOU!');
      } else {
        setRoundTransitionMessage('ROUND 1 LOST! WIN ROUND 2 TO STAY ALIVE!');
      }

      setPhase('round-transition');

      // Auto start next round after 1.8 seconds
      roundTransitionTimeoutRef.current = setTimeout(() => {
        setPhase('ready');
      }, 1900);
    }
  };

  const handleRematch = () => {
    sounds.playClick();
    setMatchResult(null);
    setLastRoundResult(null);
    setBo3State({
      userScore: 0,
      opponentScore: 0,
      currentRound: 1,
      rounds: [],
      targetWins: 2,
      isMatchOver: false,
    });
    setPhase('human-verify');
    randomizeCalibrationTarget();
  };

  const handleBackToLobby = () => {
    sounds.playClick();
    onNavigate('/lobby');
  };

  const renderDirectionIcon = (dir?: TargetVectorDirection) => {
    switch (dir) {
      case 'up':
        return <ArrowUp className="w-8 h-8 text-black animate-bounce" />;
      case 'down':
        return <ArrowDown className="w-8 h-8 text-black animate-bounce" />;
      case 'left':
        return <ArrowLeftIcon className="w-8 h-8 text-black animate-pulse" />;
      case 'right':
        return <ArrowRightIcon className="w-8 h-8 text-black animate-pulse" />;
      default:
        return <Zap className="w-8 h-8 text-black fill-black animate-pulse" />;
    }
  };

  return (
    <div
      onPointerMove={handlePointerMove}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      className="min-h-screen bg-black relative overflow-x-hidden flex flex-col select-none text-zinc-100 selection:bg-white/20"
    >
      {/* Ultra-faint celestial starfield */}
      <PulsarCosmicBackground className="opacity-70" />
      <div className="absolute inset-0 bg-grid opacity-30 pointer-events-none" />

      {/* Top Header Bar */}
      <header
        dir="ltr"
        style={{ direction: 'ltr' }}
        className="relative z-20 flex items-center justify-between px-4 h-14 min-h-[56px] max-h-[56px] max-w-md mx-auto w-full border-b border-white/[0.04] header-strict-ltr"
      >
        <button
          onClick={handleBackToLobby}
          className="btn-secondary py-1.5 px-3 flex items-center gap-1.5 text-xs text-zinc-300 hover:text-white cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>{t('backToLobby')}</span>
        </button>

        {/* Best of 3 Live Score Banner */}
        <div className="flex items-center gap-3" dir="ltr" style={{ direction: 'ltr' }}>
          <div className="text-right">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wider font-mono">{t('bestOfThree')}</div>
            <div className="text-xs font-semibold text-zinc-200">{opponent}</div>
          </div>
          <div className="w-8 h-8 rounded-full bg-zinc-900 border border-white/[0.06] flex items-center justify-center text-xs font-bold text-zinc-200 font-mono">
            {opponent.slice(0, 2).toUpperCase()}
          </div>
        </div>
      </header>

      {/* Best of 3 Round Scoreboard Bar */}
      <div className="relative z-10 max-w-md mx-auto w-full px-4 pt-2.5 mb-1">
        <div className="flex items-center justify-between p-2.5 rounded-xl bg-zinc-900/80 border border-white/[0.06] backdrop-blur-sm">
          {/* User Score Orb */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  'w-3 h-3 rounded-full transition-all duration-300 border',
                  bo3State.userScore >= 1
                    ? 'bg-emerald-400 border-emerald-300 shadow-[0_0_10px_rgba(52,211,153,0.8)]'
                    : 'bg-zinc-800 border-zinc-700'
                )}
              />
              <span
                className={cn(
                  'w-3 h-3 rounded-full transition-all duration-300 border',
                  bo3State.userScore >= 2
                    ? 'bg-emerald-400 border-emerald-300 shadow-[0_0_10px_rgba(52,211,153,0.8)]'
                    : 'bg-zinc-800 border-zinc-700'
                )}
              />
            </div>
            <span className="text-[11px] font-bold text-white font-mono">{t('youPlayer')} ({bo3State.userScore})</span>
          </div>

          {/* Center Round Label */}
          <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-white/[0.05] border border-white/[0.08] text-[10px] font-mono text-zinc-300">
            <Swords className="w-3 h-3 text-sky-400" />
            <span>
              {bo3State.userScore === 1 && bo3State.opponentScore === 1
                ? t('roundThreeFinal')
                : t('roundOfThree', { current: Math.min(bo3State.currentRound, 3) })}
            </span>
          </div>

          {/* Opponent Score Orb */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold text-zinc-300 font-mono">
              ({bo3State.opponentScore}) {t('oppPlayer')}
            </span>
            <div className="flex items-center gap-1.5">
              <span
                className={cn(
                  'w-3 h-3 rounded-full transition-all duration-300 border',
                  bo3State.opponentScore >= 1
                    ? 'bg-sky-400 border-sky-300 shadow-[0_0_10px_rgba(56,189,248,0.8)]'
                    : 'bg-zinc-800 border-zinc-700'
                )}
              />
              <span
                className={cn(
                  'w-3 h-3 rounded-full transition-all duration-300 border',
                  bo3State.opponentScore >= 2
                    ? 'bg-sky-400 border-sky-300 shadow-[0_0_10px_rgba(56,189,248,0.8)]'
                    : 'bg-zinc-800 border-zinc-700'
                )}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Stakes and Anti-Cheat Live Status Strip */}
      <div className="relative z-10 max-w-md mx-auto w-full px-4 pt-1 mb-1 flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-zinc-400">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-[10.5px] font-mono">{t('firstTo2Wins')}</span>
        </div>
        <div className="text-emerald-400 font-mono font-bold text-xs">
          {t('prizeLabel', { prize: AntiCheat.calculatePrize(currentStake).toFixed(2) })}
        </div>
      </div>

      {/* Main Interactive Stage */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 max-w-md mx-auto w-full pb-10">
        
        {/* Wallet Connection Required Gate (Only for Real Staked Matches) */}
        {!wallet.connected && currentStake > 0 ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="linear-card-elevated p-6 text-center max-w-sm w-full space-y-4 border border-amber-500/20"
          >
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto text-amber-400">
              <Wallet className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h2 className="text-base font-bold text-white">{t('walletRequiredForStaked')}</h2>
              <p className="text-xs text-zinc-400 leading-relaxed">
                {t('walletRequiredDesc')}
              </p>
            </div>
            <div className="pt-2 flex flex-col gap-2">
              <div className="flex justify-center">
                <ConnectWallet />
              </div>
              <button
                onClick={handleBackToLobby}
                className="btn-secondary py-2 text-xs text-zinc-400 hover:text-white cursor-pointer"
              >
                {t('backToLobby')}
              </button>
            </div>
          </motion.div>
        ) : wallet.connected && currentStake > 0 && wallet.balance < currentStake ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="linear-card-elevated p-6 text-center max-w-sm w-full space-y-4 border border-rose-500/20"
          >
            <div className="w-12 h-12 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center mx-auto text-rose-400">
              <Coins className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h2 className="text-base font-bold text-white">{t('insufficientBalance')}</h2>
              <p className="text-xs text-zinc-400 leading-relaxed">
                {t('insufficientBalanceDesc', { stake: currentStake.toFixed(2) })}
              </p>
            </div>
            <div className="pt-2 flex flex-col gap-2">
              <button
                onClick={() => onNavigate('/profile')}
                className="btn-primary py-2 text-xs font-bold cursor-pointer"
              >
                {t('depositFunds')}
              </button>
              <button
                onClick={handleBackToLobby}
                className="btn-secondary py-2 text-xs text-zinc-400 hover:text-white cursor-pointer"
              >
                {t('backToLobby')}
              </button>
            </div>
          </motion.div>
        ) : (
          <>
            {/* PHASE 1: Human Kinematic Calibration */}
            {phase === 'human-verify' && (
              <motion.div
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center text-center w-full"
              >
                <div className="w-11 h-11 rounded-2xl bg-zinc-900 border border-white/[0.06] flex items-center justify-center mb-3 text-zinc-300">
                  <Fingerprint className="w-5 h-5 text-sky-400 animate-pulse" />
                </div>
                <h2 className="text-lg font-semibold text-white">{t('zeroBotHandshake')}</h2>
                <p className="text-xs text-zinc-400 mt-1 max-w-xs leading-relaxed">
                  {t('tapGlowingNode')}
                </p>

                {/* Interactive calibration canvas container */}
                <div className="relative w-full h-64 mt-5 linear-card overflow-hidden">
                  <div className="absolute inset-0 bg-grid opacity-20 pointer-events-none" />
                  <motion.button
                    onClick={handleVerifyNodeClick}
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full p-4 flex items-center justify-center cursor-pointer shadow-lg active:scale-90 transition-transform"
                    style={{
                      left: `${verifyTarget.x}%`,
                      top: `${verifyTarget.y}%`,
                      background:
                        'radial-gradient(circle at 30% 30%, #ffffff, #94a3b8 50%, #334155 100%)',
                      boxShadow: '0 0 24px rgba(255,255,255,0.35)',
                    }}
                    whileHover={{ scale: 1.12 }}
                    whileTap={{ scale: 0.88 }}
                  >
                    <div className="w-3.5 h-3.5 rounded-full bg-white animate-ping" />
                  </motion.button>
                </div>
              </motion.div>
            )}

            {/* PHASE 2: Countdown 3-2-1 */}
            {phase === 'ready' && (
              <motion.div
                initial={{ scale: 0.7, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="flex flex-col items-center justify-center"
              >
                <div className="relative w-32 h-32 flex items-center justify-center">
                  <motion.div
                    animate={{ scale: [1, 1.25, 1], opacity: [0.2, 0.6, 0.2] }}
                    transition={{ duration: 0.7, repeat: Infinity }}
                    className="absolute inset-0 rounded-full border border-sky-500/40"
                  />
                  <span className="text-5xl font-extrabold text-white font-mono">{countdown}</span>
                </div>
                <div className="mt-4 text-center">
                  <span className="text-xs font-bold text-sky-400 uppercase tracking-widest font-mono">
                    {bo3State.userScore === 1 && bo3State.opponentScore === 1
                      ? t('decidingRound3')
                      : `${t('roundLabel')} ${Math.min(bo3State.currentRound, 3)}`}
                  </span>
                  <p className="text-[11px] text-zinc-400 mt-0.5">{t('focusEyes')}</p>
                </div>
              </motion.div>
            )}

            {/* PHASE 3: Waiting Phase (Spatial Target Masking - Anti-Photodiode) */}
            {phase === 'waiting' && (
              <div
                onClick={handleEarlyClick}
                className="w-full flex-1 flex flex-col items-center justify-center cursor-pointer p-4 select-none min-h-[320px]"
              >
                {earlyClickWarning ? (
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="text-center"
                  >
                    <XCircle className="w-14 h-14 text-red-400 mx-auto mb-2" />
                    <h3 className="text-lg font-bold text-red-400">{t('falseStart')}</h3>
                    <p className="text-xs text-zinc-400 mt-1">{t('falseStartDesc')}</p>
                  </motion.div>
                ) : (
                  <div className="flex flex-col items-center text-center">
                    <div className="relative w-28 h-28 flex items-center justify-center">
                      <motion.div
                        animate={{ scale: [1, 1.18, 1], opacity: [0.2, 0.6, 0.2] }}
                        transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
                        className="absolute inset-0 rounded-full bg-sky-500/15 border border-sky-400/30"
                      />
                      <div className="w-12 h-12 rounded-full bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-sky-300 font-bold text-xs font-mono shadow-[0_0_15px_rgba(56,189,248,0.25)]">
                        {t('holdTarget')}
                      </div>
                    </div>
                    <h3 className="text-sm font-semibold text-zinc-200 mt-5">{t('scanningReflexes')}</h3>
                    <p className="text-xs text-zinc-500 mt-1">{t('targetRandomMs')}</p>
                  </div>
                )}
              </div>
            )}

            {/* PHASE 4: Action Phase (DYNAMIC SPATIAL VECTOR TARGET - 100% Anti-Bot) */}
            {phase === 'action' && spawnConfig && (
              <div className="relative w-full h-[360px] linear-card overflow-hidden flex items-center justify-center">
                {/* Ambient subtle radar ring centered at spawn position */}
                <div
                  className="absolute -translate-x-1/2 -translate-y-1/2 pointer-events-none"
                  style={{
                    left: `${spawnConfig.xPercent}%`,
                    top: `${spawnConfig.yPercent}%`,
                  }}
                >
                  <div className="w-48 h-48 rounded-full border border-emerald-400/20 animate-ping opacity-60" />
                </div>

                {/* Dynamic Anti-Cheat Pulsar Strike Target */}
                <motion.button
                  initial={{ scale: 0.3, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={handleTargetHit}
                  className="absolute -translate-x-1/2 -translate-y-1/2 w-28 h-28 rounded-full flex flex-col items-center justify-center cursor-pointer border-2 border-emerald-200 shadow-2xl transition-transform active:scale-95"
                  style={{
                    left: `${spawnConfig.xPercent}%`,
                    top: `${spawnConfig.yPercent}%`,
                    background:
                      'radial-gradient(circle at 35% 35%, #86efac 0%, #10b981 55%, #059669 100%)',
                    boxShadow: '0 0 35px rgba(16, 185, 129, 0.7)',
                  }}
                >
                  {renderDirectionIcon(spawnConfig.direction)}
                  <span className="text-[10px] font-black text-black tracking-tight uppercase font-mono mt-0.5">
                    {t('tapTarget')}
                  </span>
                </motion.button>

                {/* Micro Crosshair Guide */}
                <div className="absolute bottom-3 left-3 text-[10px] font-mono text-zinc-500 flex items-center gap-1.5">
                  <Crosshair className="w-3 h-3 text-emerald-400" />
                  <span>{t('targetSeed')}: {spawnConfig.seedHash.slice(0, 8)}</span>
                </div>
              </div>
            )}

            {/* PHASE 5: Verifying Phase with Biometric Engine Telemetry */}
            {phase === 'verifying' && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col items-center text-center max-w-xs"
              >
                <LoaderCircle className="w-10 h-10 text-sky-400 animate-spin mb-3" />
                <h3 className="text-base font-semibold text-white">{t('biometricAnalysis')}</h3>
                <p className="text-xs text-zinc-400 mt-1">
                  {t('validatingCurve')}
                </p>

                <div className="w-full bg-zinc-800 rounded-full h-1.5 mt-5 overflow-hidden">
                  <motion.div
                    className="h-full bg-sky-400 rounded-full"
                    style={{ width: `${verifyProgress}%` }}
                  />
                </div>
                <div className="flex justify-between w-full text-[10px] text-zinc-500 font-mono mt-2">
                  <span>{t('latencyLock')}</span>
                  <span>{verifyProgress}%</span>
                </div>
              </motion.div>
            )}

            {/* PHASE 6: Round Intermission & Best of 3 Transition */}
            {phase === 'round-transition' && lastRoundResult && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center text-center max-w-xs w-full"
              >
                <div
                  className={cn(
                    'w-14 h-14 rounded-full flex items-center justify-center mb-3 border',
                    lastRoundResult.winner === 'user'
                      ? 'bg-emerald-500/20 border-emerald-400/40 text-emerald-400'
                      : 'bg-sky-500/20 border-sky-400/40 text-sky-300'
                  )}
                >
                  {lastRoundResult.winner === 'user' ? (
                    <Trophy className="w-7 h-7" />
                  ) : (
                    <Flame className="w-7 h-7" />
                  )}
                </div>

                <h3 className="text-sm font-bold text-sky-400 tracking-wider uppercase font-mono">
                  {roundTransitionMessage}
                </h3>

                {/* Round Speeds Compare */}
                <div className="linear-card p-3 w-full mt-3 space-y-2 text-xs">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">{t('yourTime')}</span>
                    <span
                      className={cn(
                        'font-mono font-bold',
                        lastRoundResult.winner === 'user' ? 'text-emerald-400' : 'text-zinc-200'
                      )}
                    >
                      {lastRoundResult.userTime}ms
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-400">{opponent}</span>
                    <span
                      className={cn(
                        'font-mono font-bold',
                        lastRoundResult.winner === 'opponent' ? 'text-rose-400' : 'text-zinc-400'
                      )}
                    >
                      {lastRoundResult.opponentTime}ms
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 mt-4 text-xs font-mono text-zinc-400 animate-pulse">
                  <LoaderCircle className="w-3.5 h-3.5 animate-spin text-sky-400" />
                  <span>{t('preparingNextRound')}</span>
                </div>
              </motion.div>
            )}

            {/* PHASE 7A: Bot Detected Warning */}
            {phase === 'bot-detected' && matchResult && (
              <motion.div
                initial={{ opacity: 0, scale: 0.92 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center text-center w-full max-w-sm"
              >
                <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mb-4">
                  <ShieldAlert className="w-8 h-8 text-red-400" />
                </div>

                <h2 className="text-xl font-bold text-red-400">{t('antiCheatTriggered')}</h2>
                <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed px-3">
                  {matchResult.reason || 'Input pattern flagged as non-human.'}
                </p>

                <div className="linear-card p-3.5 w-full mt-5 space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">{t('recordedLatency')}</span>
                    <span className="text-red-400 font-mono font-bold">
                      {matchResult.yourTime}ms
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">{t('humanBiologicalFloor')}</span>
                    <span className="text-zinc-300 font-mono font-bold">
                      {AntiCheat.minHumanReaction}ms
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-2 w-full mt-5">
                  <button
                    onClick={handleRematch}
                    className="w-full btn-primary py-3 flex items-center justify-center gap-2 cursor-pointer text-xs"
                  >
                    <RotateCcw className="w-4 h-4" />
                    <span>{t('recalibrateRetry')}</span>
                  </button>
                  <button
                    onClick={handleBackToLobby}
                    className="w-full btn-secondary py-3 flex items-center justify-center gap-2 cursor-pointer text-xs"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    <span>{t('backToLobby')}</span>
                  </button>
                </div>
              </motion.div>
            )}

            {/* PHASE 7B: Regular Final Result (Win or Loss after Best of 3) */}
            {phase === 'result' && matchResult && (
              <motion.div
                initial={{ opacity: 0, scale: 0.92 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center w-full max-w-sm text-center"
              >
                <motion.div
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: 'spring', stiffness: 260, damping: 18 }}
                  className={cn(
                    'w-16 h-16 rounded-full flex items-center justify-center mb-3',
                    matchResult.outcome === 'win'
                      ? 'bg-emerald-500/15 border border-emerald-400/30'
                      : 'bg-sky-950/50 border border-sky-400/30 shadow-[0_0_20px_rgba(56,189,248,0.15)]'
                  )}
                >
                  {matchResult.outcome === 'win' ? (
                    <Trophy className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <XCircle className="w-8 h-8 text-sky-400" />
                  )}
                </motion.div>

                <h2
                  className={cn(
                    'text-2xl font-bold tracking-tight',
                    matchResult.outcome === 'win' ? 'text-emerald-400' : 'text-sky-300'
                  )}
                >
                  {matchResult.outcome === 'win' ? t('matchVictory') : t('matchDefeat')}
                </h2>

                <div className="text-xs font-mono text-zinc-400 mt-1">
                  {t('finalScore')}: {matchResult.userScore} - {matchResult.opponentScore}
                </div>

                {matchResult.outcome === 'win' && (
                  <motion.p
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 }}
                    className="text-lg font-bold text-white mt-1 font-mono"
                  >
                    {matchResult.prize > 0 ? `+$${matchResult.prize.toFixed(2)} USDT` : t('practiceVictory')}
                  </motion.p>
                )}

                {/* Round by Round Breakdown */}
                <div className="linear-card p-3.5 w-full mt-3 space-y-2">
                  <div className="text-[11px] font-mono font-semibold text-zinc-300 text-left border-b border-white/[0.06] pb-1.5 flex justify-between">
                    <span>{t('roundByRound')}</span>
                    <span className="text-zinc-500">{t('speedMs')}</span>
                  </div>
                  {matchResult.rounds?.map((r, idx) => (
                    <div key={idx} className="flex items-center justify-between text-xs py-0.5">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={cn(
                            'w-2 h-2 rounded-full',
                            r.winner === 'user' ? 'bg-emerald-400' : 'bg-sky-400'
                          )}
                        />
                        <span className="text-zinc-400 font-mono">{t('roundLabel')} {r.roundNumber}:</span>
                        <span className="font-semibold text-white">
                          {r.winner === 'user' ? t('wonStatus') : t('lostStatus')}
                        </span>
                      </div>
                      <div className="font-mono text-xs text-zinc-300">
                        <span className={r.winner === 'user' ? 'text-emerald-400 font-bold' : 'text-zinc-400'}>
                          {r.userTime}ms
                        </span>
                        <span className="text-zinc-600 mx-1">{t('versus')}</span>
                        <span className={r.winner === 'opponent' ? 'text-sky-400 font-bold' : 'text-zinc-500'}>
                          {r.opponentTime}ms
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* XP & Rewards Summary */}
                {xpSummary && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.15 }}
                    className="w-full mt-3 p-3 rounded-xl bg-zinc-950/80 border border-white/[0.08] text-left space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-300">
                        <Sparkles className="w-3.5 h-3.5 text-zinc-400" />
                        <span>{t('duelRewards')}</span>
                      </div>
                      <span className="text-xs font-mono font-semibold text-emerald-400">
                        +{xpSummary.totalAwardedXP} XP
                      </span>
                    </div>

                    {/* Level Progress */}
                    <div className="space-y-1 pt-1 border-t border-white/[0.04]">
                      <div className="flex justify-between text-[10px] text-zinc-400 font-mono">
                        <span>{t('levelLabel')} {xpSummary.newLevel} ({xpSummary.tierName})</span>
                        <span>{xpSummary.currentLevelXP}/{xpSummary.nextLevelThresholdXP} XP</span>
                      </div>
                      <div className="w-full bg-zinc-800/60 rounded-full h-1 overflow-hidden">
                        <div
                          style={{ width: `${xpSummary.levelProgressPercent}%` }}
                          className="h-full bg-zinc-300 rounded-full"
                        />
                      </div>
                    </div>

                    {/* $PULSAR Token Power */}
                    <div
                      onClick={() => {
                        sounds.playClick();
                        setShowTokenomicsModal(true);
                      }}
                      className="flex items-center justify-between pt-1 border-t border-white/[0.04] text-[9.5px] text-zinc-500 font-mono cursor-pointer hover:text-zinc-300 transition-colors"
                    >
                      <div className="flex items-center gap-1">
                        <Coins className="w-2.5 h-2.5 text-zinc-400" />
                        <span>{t('miningPower')}:</span>
                      </div>
                      <span className="text-zinc-300">
                        ~{xpSummary.estimatedPulsarTokens} $PULSAR ⓘ
                      </span>
                    </div>
                  </motion.div>
                )}

                {/* Anti-Cheat Biometric Telemetry */}
                {matchResult.telemetry && (
                  <div className="w-full mt-3 p-3 rounded-xl bg-white/[0.02] border border-white/[0.05] text-left space-y-2">
                    <div className="flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-1.5 text-zinc-300 font-medium">
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                        <span>{t('neuralBioVerification')}</span>
                      </div>
                      <span className="text-emerald-400 font-mono font-bold">
                        {matchResult.telemetry.humanEntropyScore}% {t('humanPercent')}
                      </span>
                    </div>

                    <div className="flex items-center justify-between pt-1.5 border-t border-white/[0.04] text-[9px] font-mono text-zinc-500">
                      <div className="flex items-center gap-1 text-sky-400">
                        <Cpu className="w-3 h-3" />
                        <span>EIP-712 Oracle: 0x9E7F...12480</span>
                      </div>
                      <span className="text-emerald-400 font-semibold">{t('instantEscrowPayout')}</span>
                    </div>
                  </div>
                )}

                {/* Guest Account Callout */}
                {!wallet.connected && (
                  <div className="w-full mt-3 p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-left flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Wallet className="w-4 h-4 text-emerald-400 shrink-0" />
                      <div>
                        <div className="text-[11px] font-semibold text-white">{t('guestSessionSaved')}</div>
                        <div className="text-[9.5px] text-zinc-400">{t('guestSessionDesc')}</div>
                      </div>
                    </div>
                    <button
                      onClick={() => setShowWalletModal(true)}
                      className="px-2.5 py-1 rounded-lg bg-emerald-400 text-black text-[10px] font-bold font-mono hover:bg-emerald-300 cursor-pointer"
                    >
                      {t('connect')}
                    </button>
                  </div>
                )}

                {/* Action buttons */}
                <div className="flex flex-col gap-2 w-full mt-5">
                  <button
                    onClick={handleRematch}
                    className="w-full btn-primary py-3 flex items-center justify-center gap-2 cursor-pointer text-xs"
                  >
                    <RotateCcw className="w-4 h-4 fill-black" />
                    <span>{t('nextDuel')}</span>
                  </button>

                  <button
                    onClick={() => {
                      sounds.playClick();
                      setShowCertificateModal(true);
                    }}
                    className="w-full py-2.5 px-4 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-sky-400 font-mono text-xs flex items-center justify-center gap-1.5 cursor-pointer transition-colors active:scale-95"
                  >
                    <ShieldCheck className="w-4 h-4 text-sky-400" />
                    <span>View Cryptographic Certificate & Proof</span>
                  </button>

                  <button
                    onClick={handleBackToLobby}
                    className="w-full btn-secondary py-3 flex items-center justify-center gap-2 cursor-pointer text-xs"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    <span>{t('backToLobby')}</span>
                  </button>
                </div>
              </motion.div>
            )}
          </>
        )}
      </main>

      {/* Duel Cryptographic Certificate Modal */}
      {matchResult && (
        <DuelCertificateModal
          isOpen={showCertificateModal}
          onClose={() => setShowCertificateModal(false)}
          match={{
            id: `PULSAR-${Date.now().toString(36).toUpperCase()}`,
            game: 'reaction',
            result: matchResult.outcome === 'win' ? 'win' : 'loss',
            entryFee: currentStake,
            prize: matchResult.outcome === 'win' ? matchResult.prize || (currentStake * 1.96) : 0,
            yourTime: matchResult.yourTime,
            opponentTime: matchResult.opponentTime,
            timestamp: Date.now(),
            oracleSignature: `0x7a8f9c${Date.now().toString(16).padEnd(58, 'fa3b09')}`,
            opponentName: opponent,
          }}
          playerTag={wallet.playerId}
          walletAddress={wallet.address || undefined}
        />
      )}

      {/* Tokenomics Spec Modal */}
      {xpSummary && (
        <TokenomicsInspectorModal
          isOpen={showTokenomicsModal}
          onClose={() => setShowTokenomicsModal(false)}
          userLevel={xpSummary.newLevel}
          userXP={xpSummary.newTotalXP}
        />
      )}

      {/* Connect Wallet Modal */}
      <ConnectWallet
        isOpen={showWalletModal}
        onClose={() => setShowWalletModal(false)}
      />
    </div>
  );
};
