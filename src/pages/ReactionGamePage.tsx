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
import {
  gameServerConfigured,
  ensureSession,
  queueForMatch,
  cancelQueue,
  commitRound,
  revealRoundTarget,
  submitRoundResult,
  settleMatch,
  getMatch,
  matchIdToBytes32,
  type ServerSession,
  type MatchView,
} from '../lib/gameServerClient';
import {
  settleDuel as settleDuelOnChain,
  ensureDuelActive,
  getUsdtBalance,
  refundTimeoutMatch,
  validateEscrowDeployment,
} from '../lib/escrowFlow';
import { isEscrowConfigured, CHAIN, explorerTxUrl } from '../lib/chain';
import { realWeb3Manager } from '../lib/realWeb3';
import { reportError } from '../lib/monitoring';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';
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
  stakeAmount = 0,
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

  // P2.2 — Server-authoritative mode state. When a real (staked) match runs
  // through the game server, `serverMatch` holds the authoritative view and
  // every round follows the server's commit → reveal → submit protocol.
  // Practice mode (stake 0) never touches the server.
  const [serverMatch, setServerMatch] = useState<MatchView | null>(null);
  const [serverSession, setServerSession] = useState<ServerSession | null>(null);
  const [serverError, setServerError] = useState<string>('');
  const [settlementTxHash, setSettlementTxHash] = useState<string>('');
  const [refundTxHash, setRefundTxHash] = useState<string>('');
  const [claimError, setClaimError] = useState<string>('');
  const [refundError, setRefundError] = useState<string>('');
  const [claimBusy, setClaimBusy] = useState(false);
  // Any positive stake is ranked mode. Missing server configuration must fail
  // closed; it must never silently fall through to the local practice bot and
  // present a simulated result as a wagered duel.
  const isServerMode = currentStake > 0;

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
  const [xpSummary, setXpSummary] = useState<XPSummary | null>(null);

  const startTimeRef = useRef<number>(0);
  const waitTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const countdownIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const roundTransitionTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const trajectoryRef = useRef<MouseTrajectoryPoint[]>([]);
  const reactionTimeRef = useRef<number>(0);
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null);
  const targetRevealRef = useRef<number>(0); // when this round's server target appeared
  // P0-fix (audit #2): per-round proof from the reveal step. Every result
  // submission must carry it — the server rejects results without it.
  const resultProofRef = useRef<string>('');
  // Touch browsers can emit both touchend and click for one tap. Lock the
  // round synchronously so only one HTTP result submission can be started.
  const roundInputLockedRef = useRef(false);
  const pendingFalseStartRef = useRef(false);
  const serverAbortRef = useRef(false);
  const serverWaitingRef = useRef(false);
  const serverSessionRef = useRef<ServerSession | null>(null);

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

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (waitTimeoutRef.current) clearTimeout(waitTimeoutRef.current);
      if (countdownIntervalRef.current) clearInterval(countdownIntervalRef.current);
      if (roundTransitionTimeoutRef.current) clearTimeout(roundTransitionTimeoutRef.current);
      serverAbortRef.current = true;
      if (serverWaitingRef.current && serverSessionRef.current) {
        void cancelQueue(serverSessionRef.current);
      }
    };
  }, []);

  // P2.2 — Server-authoritative matchmaking for staked matches. Practice mode
  // (stake 0) never queues and never touches the server.
  const startServerMatch = useCallback(async () => {
    if (!isServerMode || !wallet.address) return;
    serverAbortRef.current = false;
    serverWaitingRef.current = false;
    setServerError('');
    setPhase('matchmaking');
    try {
      if (!gameServerConfigured()) {
        throw new Error('The game server is not configured. Ranked duels are unavailable; practice mode remains available.');
      }
      const provider = realWeb3Manager.getActiveEip1193Provider();
      if (!provider) throw new Error('No active wallet to sign in with.');
      // P0-fix (audit #2): the SIWE identity MUST be the full 40-hex address.
      // The display value (wallet.address) is `0x1234…abcd`; the server's
      // nonce endpoint requires ^0x[0-9a-fA-F]{40}$ and rejected it with 422,
      // so ranked duels died at the very first step.
      const fullAddr = wallet.fullAddress || wallet.address;
      // Validate the exact deployed contract and live token balance before we
      // occupy a queue slot and potentially strand another player.
      await validateEscrowDeployment();
      const liveBalance = Number(await getUsdtBalance(fullAddr));
      if (!Number.isFinite(liveBalance) || liveBalance < currentStake) {
        throw new Error(`Insufficient on-chain USDT balance for a $${currentStake} duel.`);
      }
      const session = await ensureSession(fullAddr, async (message: string) => {
        try {
          return await provider.request({ method: 'personal_sign', params: [message, fullAddr] });
        } catch (e: unknown) {
          const code = (e as { code?: number })?.code;
          if (code === -32601 || code === -32602) {
            return await provider.request({ method: 'signMessage', params: [fullAddr, message] });
          }
          throw e;
        }
      });
      setServerSession(session);
      serverSessionRef.current = session;
      let view = await queueForMatch(session, currentStake);
      setServerMatch(view);
      serverWaitingRef.current = view.status === 'waiting';
      // Poll while waiting in the queue (queueForMatch is idempotent: it
      // returns the caller's waiting match or their active match).
      const deadline = Date.now() + 90_000;
      while (view.status === 'waiting' && Date.now() < deadline && !serverAbortRef.current) {
        await new Promise((r) => setTimeout(r, 2500));
        if (serverAbortRef.current) break;
        view = await queueForMatch(session, currentStake);
        setServerMatch(view);
        serverWaitingRef.current = view.status === 'waiting';
      }
      if (serverAbortRef.current) {
        if (view.status === 'waiting') await cancelQueue(session);
        return;
      }
      if (view.status === 'waiting') {
        const cancellation = await cancelQueue(session);
        // If an opponent joined between the last poll and cancellation, the
        // server returns that active match and refuses to tear it down.
        if (!cancellation.cancelled && cancellation.match?.status === 'active') {
          view = cancellation.match;
        } else {
          setServerMatch(null);
          throw new Error('No opponent joined within 90 seconds. Your queue slot was released.');
        }
      }
      serverWaitingRef.current = false;
      setServerMatch(view);
      if (view.opponent) setOpponent(view.opponent);

      // Both deposits must be confirmed before either client starts round 1.
      // The helper validates participants/stake and resumes safely after a
      // refresh instead of repeating createDuel/joinDuel transactions.
      if (!isEscrowConfigured()) {
        throw new Error('Escrow is not configured — staked duels are disabled. Practice mode is available.');
      }
      const bytes32 = await matchIdToBytes32(view.matchId);
      if (!view.opponent) throw new Error('Matched opponent identity is missing.');
      await ensureDuelActive(
        bytes32,
        currentStake,
        fullAddr,
        view.opponent,
        view.youAreCreator
      );

      sounds.playMatchFound();
      setBo3State({ userScore: 0, opponentScore: 0, currentRound: 1, rounds: [], targetWins: 2, isMatchOver: false });
      setPhase('ready');
    } catch (err: unknown) {
      setClaimBusy(false);
      const msg = err instanceof Error ? err.message : String(err);
      setServerError(msg);
      setMatchResult({ outcome: 'void', yourTime: 0, opponentTime: 0, prize: 0, reason: msg });
      setPhase('bot-detected'); // honest error shell; reason is rendered
    }
  }, [isServerMode, wallet.address, wallet.fullAddress, currentStake]);

  // Auto-start server matchmaking once on mount for staked matches.
  const serverStartRef = useRef(false);
  useEffect(() => {
    if (currentStake > 0 && wallet.address && !serverStartRef.current) {
      serverStartRef.current = true;
      void startServerMatch();
    }
  }, [currentStake, wallet.address, startServerMatch]);

  // Start waiting phase — practice: local randomized delay. Server mode:
  // commit this round, fetch the server's target delay, and wait exactly that
  // long before the target appears.
  const startWaitingPhase = () => {
    setPhase('waiting');
    setEarlyClickWarning(false);
    trajectoryRef.current = [];
    resultProofRef.current = '';
    roundInputLockedRef.current = false;
    pendingFalseStartRef.current = false;

    if (isServerMode && serverSession && serverMatch) {
      const roundIndex = bo3State.currentRound - 1;
      void (async () => {
        try {
          let targetMs: number;
          let resultProof: string;
          try {
            // First attempt this round: bind a fresh intent, then get the target.
            const intent = crypto.getRandomValues(new Uint8Array(32));
            const intentHex = Array.from(intent).map((b) => b.toString(16).padStart(2, '0')).join('');
            await commitRound(serverSession, serverMatch.matchId, roundIndex, `0x${intentHex}`);
            ({ targetMs, resultProof } = await revealRoundTarget(serverSession, serverMatch.matchId, roundIndex));
          } catch {
            // False-start re-entry (or page refresh): this round is already
            // committed. Re-revealing returns the SAME target AND the SAME
            // per-player result proof — the server never re-rolls a committed
            // round, so no exploit exists.
            ({ targetMs, resultProof } = await revealRoundTarget(serverSession, serverMatch.matchId, roundIndex));
          }
          resultProofRef.current = resultProof;
          if (pendingFalseStartRef.current) {
            pendingFalseStartRef.current = false;
            void processVerification(1);
            return;
          }
          waitTimeoutRef.current = setTimeout(() => {
            const target = AntiCheat.generateTargetSpawn();
            setSpawnConfig(target);
            startTimeRef.current = performance.now();
            targetRevealRef.current = performance.now();
            setPhase('action');
            sounds.playGo();
          }, targetMs);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          setMatchResult({ outcome: 'void', yourTime: 0, opponentTime: 0, prize: 0, reason: msg });
          setPhase('bot-detected');
        }
      })();
      return;
    }

    // Practice mode: randomized delay between 1800ms - 4200ms
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
      if (isServerMode && serverSession && serverMatch) {
        if (roundInputLockedRef.current) return;
        roundInputLockedRef.current = true;
        // A false start is an invalid attempt, not a free target re-roll. If
        // reveal is still in flight, submit it as soon as its proof arrives.
        if (resultProofRef.current) void processVerification(1);
        else pendingFalseStartRef.current = true;
        return;
      }
      setTimeout(() => {
        setEarlyClickWarning(false);
        startWaitingPhase();
      }, 1400);
    }
  };

  // User touched or clicked on dynamic target
  const handleTargetHit = (e: React.MouseEvent | React.TouchEvent) => {
    if (phase !== 'action' || roundInputLockedRef.current) return;
    roundInputLockedRef.current = true;
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
    if (phase !== 'action' || !touchStartRef.current || !spawnConfig || roundInputLockedRef.current) return;
    roundInputLockedRef.current = true;
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

  // Verification stage — dual mode. Server mode: submit the measured time to
  // the authoritative engine (plausibility + timing floor enforced there) and
  // score the round from the mutually-disclosed opponent time. Practice: the
  // local anti-cheat flow with a clearly-labeled bot opponent.
  // Score one server round locally from the mutually-disclosed opponent time.
  // If the opponent hasn't submitted yet, the round shows as undecided (no
  // fabricated points) — the server's settlement remains authoritative.
  const applyServerRoundOutcome = (
    roundIndex: number,
    userTime: number,
    myValid: boolean,
    oppMs: number | null,
    opponentValid: boolean
  ) => {
    const roundWinner: 'user' | 'opponent' | 'tie' =
      !myValid
        ? opponentValid ? 'opponent' : 'tie'
        : !opponentValid
          ? 'user'
          : oppMs == null
            ? 'tie'
            : userTime < oppMs ? 'user' : userTime > oppMs ? 'opponent' : 'tie';
    const newRoundResult: RoundResult = {
      roundNumber: roundIndex + 1,
      winner: roundWinner,
      userTime,
      opponentTime: oppMs ?? 0,
    };
    const newUserScore = bo3State.userScore + (roundWinner === 'user' ? 1 : 0);
    const newOpponentScore = bo3State.opponentScore + (roundWinner === 'opponent' ? 1 : 0);
    const newRounds = [...bo3State.rounds, newRoundResult];
    const decided = newUserScore >= 2 || newOpponentScore >= 2 || newRounds.length >= 3;

    setLastRoundResult(newRoundResult);
    setBo3State({
      userScore: newUserScore,
      opponentScore: newOpponentScore,
      currentRound: roundIndex + 2,
      rounds: newRounds,
      targetWins: 2,
      isMatchOver: decided,
    });

    if (decided) {
      void finishServerMatch(newRounds, newUserScore, newOpponentScore, userTime, oppMs ?? 0);
      return;
    }

    if (roundWinner === 'user') sounds.playWin();
    else if (roundWinner === 'opponent') sounds.playHit();
    setRoundTransitionMessage(
      oppMs == null
        ? t('waitingOpponentRound')
        : newUserScore === 1 && newOpponentScore === 1
          ? 'TIE 1 - 1! DECIDING ROUND (MATCH POINT)!'
          : roundWinner === 'user'
            ? `ROUND ${roundIndex + 1} WON!`
            : `ROUND ${roundIndex + 1} LOST!`
    );
    setPhase('round-transition');
    roundTransitionTimeoutRef.current = setTimeout(() => setPhase('ready'), 1900);
  };

  // End of a server match: fetch/settle authoritatively, claim the prize
  // on-chain if the server declared us the winner, and record history.
  const finishServerMatch = async (
    rounds: RoundResult[],
    userScore: number,
    oppScore: number,
    yourTime: number,
    oppTime: number
  ): Promise<void> => {
    if (!serverSession || !serverMatch) return;
    try {
      const view = await getMatch(serverSession, serverMatch.matchId);
      setServerMatch(view);
      if (view.status === 'void') {
        setMatchResult({
          outcome: 'void',
          yourTime,
          opponentTime: oppTime,
          prize: 0,
          reason: 'Match voided — stakes are refundable on-chain.',
          rounds,
          userScore,
          opponentScore: oppScore,
        });
        sounds.playLoss();
        setPhase('result');
        return;
      }
      // settleMatch is idempotent server-side: when the opponent settled
      // first, the SAME oracle-signed settlement is replayed to us.
      const result = await settleMatch(serverSession, serverMatch.matchId);
      if (result.status !== 'settled') {
        setMatchResult({
          outcome: 'void',
          yourTime,
          opponentTime: oppTime,
          prize: 0,
          reason: 'Match could not be settled — stakes are refundable on-chain.',
          rounds,
          userScore,
          opponentScore: oppScore,
        });
        sounds.playLoss();
        setPhase('result');
        return;
      }
      // P0-fix (audit #2): compare against the FULL wallet identity — the
      // truncated display address can never equal the settlement's winner.
      const myFull = (wallet.fullAddress || wallet.address || '').toLowerCase();
      const iWon = result.winner.toLowerCase() === myFull;
      const prize = iWon ? Math.round(currentStake * 2 * 0.98 * 100) / 100 : 0;

      // Winner submits the oracle-signed proof to release the pot.
      let txHash = '';
      if (iWon) {
        try {
          setClaimBusy(true);
          setClaimError('');
          const bytes32 = await matchIdToBytes32(result.matchId);
          txHash = await settleDuelOnChain({
            matchId: bytes32,
            winner: result.winner,
            winnerTimeMs: result.winnerTimeMs,
            loserTimeMs: result.loserTimeMs,
            nonce: result.serverNonce.toString(),
            deadline: result.deadline,
            signature: result.signature,
          });
          setSettlementTxHash(txHash);
          setClaimBusy(false);
          sounds.playWin();
          try {
            confetti({ particleCount: 90, spread: 75, origin: { y: 0.6 }, colors: ['#38bdf8', '#10b981', '#ffffff', '#eab308'] });
          } catch {}
        } catch (err: unknown) {
          // On-chain claim failed — the signed proof stays valid for 10 minutes.
          const msg = err instanceof Error ? err.message : String(err);
          setClaimBusy(false);
          setClaimError(msg);
          setMatchResult({
            outcome: iWon ? 'win' : 'loss',
            yourTime,
            opponentTime: oppTime,
            prize,
            reason: `On-chain claim failed: ${msg}. The signed proof remains claimable for 10 minutes.`,
            rounds,
            userScore,
            opponentScore: oppScore,
          });
          setPhase('result');
          return;
        }
      } else {
        sounds.playLoss();
      }

      const avgUser = Math.round(rounds.reduce((a, r) => a + r.userTime, 0) / Math.max(rounds.length, 1));
      const avgOpp = Math.round(rounds.reduce((a, r) => a + r.opponentTime, 0) / Math.max(rounds.length, 1));
      setMatchResult({
        outcome: iWon ? 'win' : 'loss',
        yourTime: avgUser,
        opponentTime: avgOpp,
        prize,
        rounds,
        userScore,
        opponentScore: oppScore,
      });

      void recordMatch({
        id: result.matchId,
        game: 'Reaction Duel (Ranked · Bo3)',
        result: iWon ? 'win' : 'loss',
        entryFee: currentStake,
        prize,
        opponentTime: avgOpp,
        yourTime: avgUser,
        timestamp: Date.now(),
        hash: txHash || undefined,
        oracleSignature: result.signature,
      }).then((xpRes) => setXpSummary(xpRes));

      setPhase('result');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setMatchResult({ outcome: 'void', yourTime, opponentTime: oppTime, prize: 0, reason: msg });
      setPhase('bot-detected');
    }
  };

  const retrySettlementClaim = (): void => {
    if (!matchResult || !serverMatch || !serverSession || claimBusy) return;
    void finishServerMatch(
      matchResult.rounds || bo3State.rounds,
      matchResult.userScore ?? bo3State.userScore,
      matchResult.opponentScore ?? bo3State.opponentScore,
      matchResult.yourTime,
      matchResult.opponentTime
    );
  };

  const requestTimeoutRefund = async (): Promise<void> => {
    if (!serverMatch) return;
    setRefundError('');
    try {
      const bytes32 = await matchIdToBytes32(serverMatch.matchId);
      setRefundTxHash(await refundTimeoutMatch(bytes32));
    } catch (err: unknown) {
      setRefundError(err instanceof Error ? err.message : String(err));
    }
  };

  const processVerification = async (timeMs: number, eventCheck?: { isTrusted: boolean; pointerType?: string; hasNaturalJitter: boolean }) => {
    setPhase('verifying');
    setVerifyProgress(0);

    const progressInterval = setInterval(() => {
      setVerifyProgress((prev) => Math.min(prev + 20, 92));
    }, 70);

    const userTime = Math.round(timeMs);

    if (isServerMode && serverSession && serverMatch) {
      const roundIndex = bo3State.currentRound - 1;
      try {
        // P0-fix (audit #2): the result MUST carry the per-player proof issued
        // at reveal — without it the server rejects the submission outright.
        const res = await submitRoundResult(serverSession, serverMatch.matchId, roundIndex, userTime, resultProofRef.current || undefined);
        // Refresh the authoritative view. Once both players submitted this
        // round it includes the opponent's validity and, when valid, their
        // time. Validity is necessary to distinguish "still playing" from an
        // invalid result; treating both as a missing time deadlocked the UI.
        const view = await getMatch(serverSession, serverMatch.matchId);
        setServerMatch(view);
        clearInterval(progressInterval);
        setVerifyProgress(100);
        if (!res.accepted) sounds.playLoss();

        const finishRoundFromView = (current: MatchView): boolean => {
          const key = String(roundIndex);
          const opponentRound = current.opponentRounds[key];
          if (!opponentRound?.submitted) return false;
          const raw = current.opponentTimes[key];
          const opponentTime = raw != null ? Math.round(raw) : null;
          applyServerRoundOutcome(
            roundIndex,
            userTime,
            res.accepted,
            opponentTime,
            opponentRound.valid
          );
          return true;
        };

        if (finishRoundFromView(view)) return;

        setRoundTransitionMessage(
          res.accepted ? t('waitingOpponentRound') : t('roundRejected', { reason: res.reason || '' })
        );
        setPhase('round-transition');
        let pollDelay = 1500;
        const pollOpponent = () => {
          roundTransitionTimeoutRef.current = setTimeout(() => {
            void (async () => {
              try {
                const latest = await getMatch(serverSession, serverMatch.matchId);
                setServerMatch(latest);
                if (finishRoundFromView(latest)) return;
                if (latest.status === 'settled' || latest.status === 'void') {
                  await finishServerMatch(
                    bo3State.rounds,
                    bo3State.userScore,
                    bo3State.opponentScore,
                    userTime,
                    0
                  );
                  return;
                }
              } catch {
                // Transient network failure: retry until the authoritative
                // grace-window finalizer returns settled/void.
              }
              pollDelay = Math.min(pollDelay * 1.5, 10000);
              pollOpponent();
            })();
          }, pollDelay);
        };
        pollOpponent();
        return;
      } catch (err: unknown) {
        clearInterval(progressInterval);
        reportError(err, { where: 'serverRoundSubmit', matchId: serverMatch.matchId, roundIndex });
        const msg = err instanceof Error ? err.message : String(err);
        setMatchResult({ outcome: 'void', yourTime: userTime, opponentTime: 0, prize: 0, reason: msg });
        setPhase('bot-detected');
        return;
      }
    }

    await AntiCheat.simulateServerDelay(650, 1000);
    clearInterval(progressInterval);
    setVerifyProgress(100);

    // Practice mode: Gaussian tier-based opponent simulation
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

    // Three exact/double-forfeit ties can exhaust the Bo3 without either side
    // reaching two wins. Finish as void instead of advancing to round 4.
    const isMatchDecided = newUserScore >= 2 || newOpponentScore >= 2 || newRounds.length >= 3;

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
      const finalWinner: MatchResolution['outcome'] =
        newUserScore >= 2 ? 'win' : newOpponentScore >= 2 ? 'loss' : 'void';
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
    setClaimError('');
    setRefundError('');
    setSettlementTxHash('');
    setRefundTxHash('');
    setBo3State({
      userScore: 0,
      opponentScore: 0,
      currentRound: 1,
      rounds: [],
      targetWins: 2,
      isMatchOver: false,
    });
    if (isServerMode) {
      // A ranked rematch is a new server/on-chain match, not round 1 of the
      // already-settled match still held in component state.
      setServerMatch(null);
      serverStartRef.current = true;
      void startServerMatch();
      return;
    }
    setPhase('human-verify');
    randomizeCalibrationTarget();
  };

  const handleBackToLobby = () => {
    sounds.playClick();
    serverAbortRef.current = true;
    if (serverWaitingRef.current && serverSessionRef.current) {
      void cancelQueue(serverSessionRef.current);
    }
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
            <div className="text-xs font-semibold text-zinc-200">
              {isServerMode && opponent.startsWith('0x')
                ? `${opponent.slice(0, 6)}...${opponent.slice(-4)}`
                : opponent}
            </div>
            {isServerMode ? (
              <div className="text-[9px] text-emerald-400/90 font-mono">{t('serverModeLabel')}</div>
            ) : (
              <div className="text-[9px] text-amber-400/90 font-mono">{t('practiceModeLabel')}</div>
            )}
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
          {isServerMode
            ? t('prizeLabel', { prize: (currentStake * 2 * 0.98).toFixed(2) })
            : t('prizeLabel', { prize: AntiCheat.calculatePrize(currentStake).toFixed(2) })}
        </div>
      </div>

      {/* Main Interactive Stage */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 max-w-md mx-auto w-full pb-10">
        
        {/* PHASE 0: Server Matchmaking (real staked matches) */}
        {phase === 'matchmaking' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col items-center text-center max-w-xs"
          >
            <LoaderCircle className="w-10 h-10 text-emerald-400 animate-spin mb-3" />
            <h3 className="text-base font-semibold text-white">{t('serverMatchmaking')}</h3>
            <p className="text-xs text-zinc-400 mt-1 animate-pulse">{t('serverWaitingOpponent')}</p>
            <div className="mt-4 text-[10px] font-mono text-zinc-500 flex items-start gap-1.5 text-left">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-px" />
              <span>{t('serverModeNote')}</span>
            </div>
          </motion.div>
        )}

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

                <h2 className="text-xl font-bold text-red-400">
                  {isServerMode ? t('serverConnError') : t('antiCheatTriggered')}
                </h2>
                <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed px-3">
                  {matchResult.reason || 'Input pattern flagged as non-human.'}
                </p>
                {isServerMode && (
                  <p className="text-[10px] font-mono text-zinc-500 mt-2 px-3">
                    {t('serverModeNote')}
                  </p>
                )}
                {isServerMode && serverMatch && (
                  <div className="w-full mt-3 space-y-2">
                    <button onClick={() => void requestTimeoutRefund()} className="w-full btn-secondary py-2.5 text-xs cursor-pointer">
                      Request on-chain timeout refund
                    </button>
                    {refundError && <p className="text-[10px] text-amber-400">{refundError}</p>}
                    {refundTxHash && <a className="text-[10px] text-sky-400 underline" href={explorerTxUrl(refundTxHash)} target="_blank" rel="noreferrer">Refund transaction ↗</a>}
                  </div>
                )}

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
                  {matchResult.outcome === 'win'
                    ? t('matchVictory')
                    : matchResult.outcome === 'void'
                      ? t('matchVoid')
                      : t('matchDefeat')}
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
                    {isServerMode && matchResult.prize > 0 && settlementTxHash ? (
                      t('prizeClaimed')
                    ) : matchResult.prize > 0 ? (
                      `+$${matchResult.prize.toFixed(2)} USDT`
                    ) : (
                      t('practiceVictory')
                    )}
                  </motion.p>
                )}
                {isServerMode && matchResult.outcome === 'win' && matchResult.prize > 0 && !settlementTxHash && (
                  claimError ? (
                    <div className="w-full mt-2 space-y-1">
                      <p className="text-[10px] text-amber-400 font-mono">{claimError}</p>
                      <button disabled={claimBusy} onClick={retrySettlementClaim} className="w-full btn-primary py-2 text-xs disabled:opacity-50 cursor-pointer">
                        {claimBusy ? t('claimingPrize') : 'Retry on-chain claim'}
                      </button>
                    </div>
                  ) : <p className="text-[10px] text-amber-400/90 font-mono mt-1">{t('claimingPrize')}</p>
                )}
                {settlementTxHash && (
                  <a
                    href={explorerTxUrl(settlementTxHash)}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] font-mono text-sky-400 hover:text-sky-300 underline mt-1 cursor-pointer"
                  >
                    {settlementTxHash.slice(0, 10)}...{settlementTxHash.slice(-8)} ↗
                  </a>
                )}
                {isServerMode && serverMatch && matchResult.outcome === 'void' && (
                  <div className="w-full mt-2 space-y-1">
                    <button onClick={() => void requestTimeoutRefund()} className="w-full btn-secondary py-2 text-xs cursor-pointer">
                      Request on-chain timeout refund
                    </button>
                    {refundError && <p className="text-[10px] text-amber-400">{refundError}</p>}
                    {refundTxHash && <a className="text-[10px] text-sky-400 underline" href={explorerTxUrl(refundTxHash)} target="_blank" rel="noreferrer">Refund transaction ↗</a>}
                  </div>
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
                          {r.winner === 'user'
                            ? t('wonStatus')
                            : r.winner === 'tie'
                              ? t('tiedStatus')
                              : t('lostStatus')}
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
                        <span>{t('offChainNote')}</span>
                      </div>
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
            id: serverMatch?.matchId || `PULSAR-${Date.now().toString(36).toUpperCase()}`,
            game: 'reaction',
            result: matchResult.outcome,
            entryFee: currentStake,
            prize: matchResult.outcome === 'win' ? matchResult.prize || (currentStake * 1.96) : 0,
            yourTime: matchResult.yourTime,
            opponentTime: matchResult.opponentTime,
            timestamp: Date.now(),
            opponentName: opponent,
            hash: settlementTxHash || undefined,
          }}
          playerTag={wallet.playerId}
          walletAddress={wallet.address || undefined}
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
