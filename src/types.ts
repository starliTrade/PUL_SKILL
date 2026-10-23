export interface WalletState {
  connected: boolean;
  provider: string | null;
  address: string;
  fullAddress?: string;
  playerId?: string;
  balance: number;
  balancePOL?: number;
  /** F-18: true until a live on-chain balance fetch succeeds. */
  balanceUnknown?: boolean;
}

export interface UserStats {
  balance: number;
  /** F-18: true until a live on-chain balance fetch succeeds — a zero
   *  balance is then an RPC failure, not a fact. */
  balanceUnknown?: boolean;
  wins: number;
  losses: number;
  voids: number;
  totalMatches: number;
  xp: number;
  level: number;
  /** Audit M31: server-authoritative win streak. */
  winStreak?: number;
  playerId?: string;
  bestReactionMs?: number;
  avgReactionMs?: number;
  /** Audit M-14: provenance of the numbers above (see UserWalletData). */
  progressionSource?: 'server' | 'local' | 'unknown';
  progressionCheckedAt?: number;
}

export interface MatchHistoryItem {
  id: string;
  game: string;
  result: 'win' | 'loss' | 'void';
  entryFee: number;
  prize: number;
  opponentTime: number;
  yourTime: number;
  timestamp: number;
  xpEarned?: number;
  /** Audit M39: the on-chain settlement tx hash, when the duel settled on
   *  chain. `DuelCertificateModal` renders the verifiable proof from this —
   *  without it every certificate claimed "NOT ON-CHAIN" even for settled
   *  duels. Absent for practice/local results. */
  hash?: string;
  /** Audit 9.6: the oracle's signature over the settled result — the
   *  cryptographic proof the certificate is supposed to show. Set only for a
   *  duel the server settled. */
  oracleSignature?: string;
  /** Audit M31: true for a duel the SERVER settled (ranked). Only then is the
   *  ledger's progression authoritative for this match; practice results have
   *  no settlement behind them and must not be reconciled against it. */
  ranked?: boolean;
}

export interface MouseTrajectoryPoint {
  x: number;
  y: number;
  t: number;
}

/**
 * Audit H16 — only what is actually MEASURED.
 *
 * This used to carry `humanEntropyScore`, `fittsKinematicScore`,
 * `neuromuscularJitterHz` and `subMillisecondClockIntegrity`. None of them was a
 * measurement: the first two were lookup tables on the reaction time, the third
 * was `3.8 + sin(reactionTimeMs * 0.05) * 1.8` (a sine wave of the clock), and
 * the fourth was always `true`. Under D1 (real money) a player shown "Human
 * Entropy 96.5%" believes the game verified something — and a false claim of
 * verification is a claim the operator cannot defend.
 *
 * What remains is real: the trajectory curvature computed from the sampled
 * points, how many samples were seen, and whether the event passed the checks
 * that exist (`isTrusted`, the human floor, the trajectory analysis).
 */
export interface BiometricTelemetry {
  trajectoryCurvature: number; // curvature variance, from the sampled points
  sampleCount: number;
  passedValidation: boolean;
  flagReason?: string;
}

export interface RoundResult {
  roundNumber: number;
  winner: 'user' | 'opponent' | 'tie';
  userTime: number;
  opponentTime: number;
}

export interface BestOfThreeState {
  userScore: number;
  opponentScore: number;
  currentRound: number;
  rounds: RoundResult[];
  targetWins: number;
  isMatchOver: boolean;
}

export interface MatchResolution {
  /**
   * Audit M-06 (2026-10-22): `pending` is NOT a synonym for `void`.
   *
   * `void` means the server decided the duel was refunded. `pending` means the
   * client stopped waiting before the server decided — the money outcome is
   * unknown, and the UI must say so instead of showing a loss. The old code
   * turned a 120-second local timeout into `outcome: 'void'`, which the result
   * screen rendered as "Defeat" and the certificate recorded as a loss.
   */
  outcome: 'win' | 'loss' | 'void' | 'pending';
  yourTime: number;
  opponentTime: number;
  prize: number;
  reason?: string;
  telemetry?: BiometricTelemetry;
  rounds?: RoundResult[];
  userScore?: number;
  opponentScore?: number;
}

export type TargetVectorDirection = 'up' | 'down' | 'left' | 'right' | 'tap';

export type GamePhase =
  | 'human-verify'
  | 'ready'
  | 'waiting'
  | 'action'
  | 'early-click'
  | 'verifying'
  | 'round-transition'
  | 'result'
  | 'bot-detected'
  | 'matchmaking';

