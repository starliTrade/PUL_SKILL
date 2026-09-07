export interface WalletState {
  connected: boolean;
  provider: string | null;
  address: string;
  fullAddress?: string;
  playerId?: string;
  balance: number;
  balancePOL?: number;
}

export interface UserStats {
  balance: number;
  wins: number;
  losses: number;
  voids: number;
  totalMatches: number;
  xp: number;
  level: number;
  playerId?: string;
  bestReactionMs?: number;
  avgReactionMs?: number;
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
}

export interface MouseTrajectoryPoint {
  x: number;
  y: number;
  t: number;
}

export interface BiometricTelemetry {
  humanEntropyScore: number; // 0 - 100%
  trajectoryCurvature: number; // curvature variance
  fittsKinematicScore: number; // Neuromuscular acceleration bell curve (0 - 100%)
  neuromuscularJitterHz: number; // Natural 2-8 Hz hand tremor frequency
  subMillisecondClockIntegrity: boolean;
  sampleCount: number;
  accelerationSmoothness: number;
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
  outcome: 'win' | 'loss' | 'void';
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
  | 'bot-detected';

