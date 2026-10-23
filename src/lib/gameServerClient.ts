import { sha256Hex } from './sha256';

/**
 * P2.1 — Typed bridge to the authoritative PULSAR game server (api/).
 *
 * Trust model (matches the P1 audit):
 *  - Identity: SIWE (EIP-4361). The client asks for a nonce, asks the wallet to
 *    sign the exact message, and exchanges it for a Bearer session token.
 *  - Results: every round flows through the server's commit → reveal → submit
 *    protocol. The client NEVER decides match outcomes; it only measures its
 *    own reaction time and submits it. The server validates plausibility and
 *    settles (P1.12/1.13). The settlement response carries the oracle
 *    signature (P1.14) that the winner submits on-chain via escrowFlow.
 *  - Practice mode never talks to this server; it uses the local bot flow and
 *    is labeled as practice in the UI.
 *
 * This client degrades gracefully: when no server URL is configured the app
 * stays in practice mode. It never fakes a server response.
 */

const _env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};
// Canonical: VITE_GAME_SERVER_URL. VITE_API_URL is accepted as a legacy alias
// (ops set it in several runbooks) — either one configures the server bridge.
const SERVER_URL: string = (
  _env.VITE_GAME_SERVER_URL || _env.VITE_API_URL || ""
).replace(/\/+$/, "");

export const gameServerConfigured = (): boolean => SERVER_URL.length > 0;

export class GameServerUnavailableError extends Error {
  constructor(public readonly cause?: unknown) {
    super(
      "The game server is not configured. Real-money duels require VITE_GAME_SERVER_URL; practice mode remains available."
    );
    this.name = "GameServerUnavailableError";
  }
}

// --- Session ----------------------------------------------------------------

const SESSION_KEY = "pulsar.server.session.v1";

export interface ServerSession {
  address: string; // lowercase
  token: string;
  issuedAt: number;
}

export const loadServerSession = (): ServerSession | null => {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as ServerSession;
    // Audit #11 M1: the server (api/auth.py SESSION_TTL_SECONDS) expires the
    // bearer token after 2 HOURS — the old 23h client window kept a session
    // the server had already revoked, so every call 401'd until the user
    // manually reconnected. Treat 1h55m as stale (5 min skew headroom) so
    // ensureSession() re-runs the SIWE handshake BEFORE the token dies.
    const SERVER_TTL_MS = 2 * 60 * 60 * 1000;
    const SKEW_MS = 5 * 60 * 1000;
    if (Date.now() - s.issuedAt > SERVER_TTL_MS - SKEW_MS) return null;
    return s;
  } catch {
    return null;
  }
};

const persistSession = (s: ServerSession): void => {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(s));
  } catch {
    // storage unavailable — session stays in-memory for this page load
  }
};

/**
 * Revoke the server session and drop it locally (audit H22b).
 *
 * H22 added `POST /api/auth/logout` so a stolen bearer token cannot stay valid
 * for its full 2h TTL. Nothing called it, so disconnecting the wallet dropped
 * the LOCAL session while the token stayed live server-side.
 *
 * The local session is cleared even when the request fails: the player asked to
 * disconnect, and a network error must not leave them holding a session they
 * cannot get rid of. The token then expires on its own TTL.
 */
export const logoutServerSession = async (): Promise<void> => {
  const session = loadServerSession();
  if (!session) return;

  try {
    await fetch(`${SERVER_URL}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
    });
  } catch {
    // Offline or the server is down — the local clear below still happens.
  } finally {
    clearServerSession();
  }
};

export const clearServerSession = (): void => {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
};

export interface SignMessageFn {
  (message: string): Promise<string>; // resolves with the wallet signature
}

/**
 * Full SIWE handshake: nonce → wallet signature → Bearer session.
 * `signMessage` is injected so this module stays decoupled from any
 * particular wallet connector.
 */
export const authenticate = async (address: string, signMessage: SignMessageFn): Promise<ServerSession> => {
  if (!gameServerConfigured()) throw new GameServerUnavailableError();

  // 1. nonce + canonical message from the server
  const nonceRes = await fetch(`${SERVER_URL}/api/auth/nonce`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ address }),
  });
  if (!nonceRes.ok) throw new Error(`Nonce request failed (${nonceRes.status})`);
  const { message } = (await nonceRes.json()) as { nonce: string; message: string };

  // 2. the wallet signs the SERVER's message (not a locally-built one) so the
  //    domain binding is always the server's canonical form.
  const signature = await signMessage(message);
  if (!signature) throw new Error("Wallet signature was rejected or empty.");

  // 3. exchange for a session token
  const verifyRes = await fetch(`${SERVER_URL}/api/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, signature }),
  });
  if (!verifyRes.ok) throw new Error(`Sign-in failed (${verifyRes.status})`);
  const { token, address: recovered } = (await verifyRes.json()) as { token: string; address: string };
  if (!token || recovered.toLowerCase() !== address.toLowerCase()) {
    throw new Error("Server session does not match the connected wallet.");
  }

  const session: ServerSession = { address: address.toLowerCase(), token, issuedAt: Date.now() };
  persistSession(session);
  return session;
};

/** Reuse a cached session, or run the SIWE handshake. */
export const ensureSession = async (address: string, signMessage: SignMessageFn): Promise<ServerSession> => {
  const cached = loadServerSession();
  if (cached && cached.address === address.toLowerCase()) return cached;
  return authenticate(address, signMessage);
};

// --- Responsible gaming (plan item 11.3 / G3) --------------------------------

export interface GamingLimits {
  depositLimit: number | null;
  pendingLimit: number | null;
  pendingLimitAt: number | null;
  excludedUntil: number;
  cooloffUntil: number;
  selfExcluded: boolean;
  coolingOff: boolean;
}

export const fetchLimits = (session: ServerSession): Promise<GamingLimits> =>
  request<GamingLimits>("/api/limits", undefined, session, "GET");

/**
 * Set a deposit ceiling.
 *
 * `null` clears it. The server decides what is immediate: lowering and clearing
 * take effect at once, RAISING waits (api/limits.py) — because a limit a player
 * can raise the moment they want to breach it is not a limit. The UI must say
 * which happened rather than implying both are instant.
 */
export const setDepositLimit = (session: ServerSession, limit: number | null): Promise<GamingLimits> =>
  request<GamingLimits>("/api/limits/deposit", { limit }, session);

/** Exclude yourself from staked play. Cannot be lifted early, by design. */
export const selfExclude = (session: ServerSession, seconds: number): Promise<GamingLimits> =>
  request<GamingLimits>("/api/limits/self-exclude", { seconds }, session);

/** A short, immediate pause. */
export const coolOff = (session: ServerSession, seconds: number): Promise<GamingLimits> =>
  request<GamingLimits>("/api/limits/cool-off", { seconds }, session);

/**
 * Record the player's eligibility attestation SERVER-SIDE (plan item 11.3/G2).
 *
 * The client gate is one localStorage key — its own comment says clearing storage
 * bypasses it. A gate a player can remove with a devtools command is not a gate,
 * so the server records the attestation against the authenticated address and
 * refuses staked play without it.
 *
 * Idempotent: confirming twice is a no-op, so this is safe on every entry.
 */
export const confirmEligibility = async (session: ServerSession): Promise<void> => {
  await request<{ ok: boolean }>("/api/eligibility/confirm", { ageConfirmed: true }, session);
};

// --- Authenticated request helper -------------------------------------------

// P0-fix — typed request method. The old helper sent POST for EVERY call,
// including getMatch(), which the server only exposes as GET → 405
// Method Not Allowed on the first in-game refresh, cutting the round flow.
// Verbs are now explicit per call so client/server can never drift again.
type RequestMethod = "GET" | "POST" | "PUT";

export class RateLimitedError extends Error {
  /** Seconds the server asks us to wait before retrying (audit #7 R3). */
  readonly retryAfterSeconds: number;

  constructor(detail: string, retryAfterSeconds: number) {
    super(detail);
    this.name = "RateLimitedError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const request = async <T>(
  path: string,
  body: unknown,
  session: ServerSession,
  method: RequestMethod = "POST"
): Promise<T> => {
  const res = await fetch(`${SERVER_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.token}`,
    },
    // GET requests must carry no body (a GET body is dropped/forbidden and
    // made this call fail some proxies before the 405 was even fixed).
    body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
  });
  if (res.status === 401) {
    clearServerSession();
    throw new Error("Your game-server session expired. Please sign in again.");
  }
  if (res.status === 429) {
    // Audit #7 R3: the server supplies Retry-After; parse it so the caller
    // can back off by contract instead of hitting a wall mid-matchmaking.
    let detail = "Rate limit exceeded";
    let retryAfter = 10;
    try {
      const err = (await res.json()) as { detail?: string };
      if (err?.detail) detail = err.detail;
    } catch {
      /* keep defaults */
    }
    const ra = res.headers.get("retry-after");
    const parsed = ra ? Number.parseFloat(ra) : NaN;
    if (Number.isFinite(parsed) && parsed >= 0) retryAfter = parsed;
    throw new RateLimitedError(detail, retryAfter);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = (await res.json()) as { detail?: string };
      if (err?.detail) detail = err.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
};

// --- Match API ---------------------------------------------------------------

export interface MatchView {
  matchId: string;
  stake: number;
  status: "waiting" | "active" | "settled" | "void";
  winner: string;
  createdAt: number;
  rounds: number;
  me: string | null;
  opponentJoined: boolean;
  opponent: string | null;
  opponentSubmitted: number;
  /** True when the caller queued first — they deposit the escrow stake via createDuel. */
  youAreCreator: boolean;
  /** Opponent's valid times, disclosed only for rounds BOTH players submitted. */
  opponentTimes: Record<string, number>;
  /** This player's own validated times per round (0..2) — rebuilds the local scoreboard after a refresh. */
  myTimes: Record<string, number>;
  myRounds: {
    index: number;
    committed: boolean;
    targetRevealed: boolean;
    submitted: boolean;
    valid: boolean;
    rejectReason: string;
  }[];
}

/**
 * Enter the matchmaking queue for a stake. Resolves when paired (server side).
 *
 * Audit M27: `opponent` is the address a friend challenge is reserved for. The
 * server will not offer that match to anyone else, and it is satisfied when the
 * named address queues. Omit it for ordinary matchmaking.
 */
export const queueForMatch = (
  session: ServerSession,
  stake: number,
  rttMs: number,
  opponent?: string
): Promise<MatchView> =>
  // Audit H1: the ping cap is evaluated at queue time.
  // Audit H-03 (2026-10-22): `rttMs` is REQUIRED — the server refuses a queue
  // request without it, because an omittable field is a skippable gate. Every
  // caller measures with `measureServerRttMs` (the zero-I/O `/api/ping`).
  request<MatchView>("/api/queue", { stake, rttMs, opponent }, session);

export const getMatch = (session: ServerSession, matchId: string): Promise<MatchView> =>
  request<MatchView>(`/api/match/${encodeURIComponent(matchId)}`, undefined, session, "GET");

/** One settled duel, as the PUBLIC settlement log publishes it. */
export interface SettlementRecord {
  matchId: string;
  stake: number;
  players: string[];
  winner: string;
  settledAt: number;
  winnerTimeMs: number | null;
  loserTimeMs: number | null;
  prize: number;
  oracleAddress: string;
  signature: string;
  settlementTx?: string;
}

/**
 * The public settlement log (audit H-04, 2026-10-22).
 *
 * The lobby's "LIVE ARENA" feed used to subscribe to a Firestore collection the
 * SERVER never writes in that shape (it reads `entryFee`, the ledger writes
 * `stake`), so the feed was permanently empty — and every row defaulted to
 * `result: 'win'` if it had ever rendered. This reads the server's own log,
 * which is public on purpose: each entry carries the oracle signature the
 * contract accepted, so the feed is verifiable rather than a claim.
 *
 * Unauthenticated: a settlement log that needs a login is not a public log.
 */
export const fetchRecentSettlements = async (limit = 15): Promise<SettlementRecord[]> => {
  if (!gameServerConfigured()) return [];
  const res = await fetch(`${SERVER_URL}/api/settlements?limit=${Math.max(1, Math.min(limit, 50))}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`settlements answered ${res.status}`);
  const body = (await res.json()) as { available?: boolean; settlements?: SettlementRecord[] };
  if (!body.available) return [];
  return Array.isArray(body.settlements) ? body.settlements : [];
};

/** A player's server-authoritative progression (audit M31). */
export interface PlayerStats {
  wins: number;
  losses: number;
  voids: number;
  totalMatches: number;
  xp: number;
  level: number;
  winStreak: number;
  bestReactionMs: number;
  avgReactionMs: number;
  lastXpAwarded?: number;
}

export type PlayerStatsResponse = ({ available: true } & PlayerStats) | { available: false };

/**
 * Read the ledger's view of a player's progression (audit M31).
 *
 * `available: false` means the ledger could not answer. The caller must fall
 * back to its local estimate — reporting zeros as facts would tell a player
 * with a hundred wins that they have never played.
 */
export const fetchPlayerStats = (
  session: ServerSession,
  address: string
): Promise<PlayerStatsResponse> =>
  request<PlayerStatsResponse>(
    `/api/player/${encodeURIComponent(address)}/stats`,
    undefined,
    session,
    "GET"
  );

/** A friend challenge waiting for the caller (audit M27 closure). */
export interface PendingChallenge {
  matchId: string;
  address: string;
  stake: number;
}

export interface PendingChallengesResponse {
  available: boolean;
  challenges: PendingChallenge[];
}

/**
 * Who is waiting for the caller (audit M27 closure).
 *
 * A reservation the target cannot discover is a duel that never happens. This
 * is the read side of `queueForMatch(..., opponent)`.
 */
export const fetchPendingChallenges = (session: ServerSession): Promise<PendingChallengesResponse> =>
  request<PendingChallengesResponse>("/api/challenges", undefined, session, "GET");

/**
 * Ask the SERVER whether a username is free (audit M12, 2026-10-13).
 *
 * The registry endpoint existed and was tested but nothing called it, so the
 * authoritative check (and its rate limit) protected nothing. The response
 * deliberately does NOT include the owner's address — only whether the name is
 * free, taken, or already yours.
 */
export const checkUsername = (
  session: ServerSession,
  name: string
): Promise<{ available: boolean; username: string; taken?: boolean; alreadyOwned?: boolean }> =>
  request("/api/username/" + encodeURIComponent(name), undefined, session, "GET");

/**
 * Report a match for operator review (phase 6.4 / G8).
 *
 * Audit 2026-10-13: the endpoint existed, was tested, and had NO client path —
 * a player could not file the report the feature is named for. This is the
 * H22b class again (a mechanism in one layer with no consumer in another).
 *
 * A report is a request for review: it never touches match state or the money
 * path, and only a participant may file one.
 */
export interface DisputeReport {
  id: string;
  reason: string;
  filedAt: number;
  /** `open` until an operator answers it (audit L-09). */
  status: "open" | "resolved" | "dismissed" | string;
  resolution?: string | null;
  resolvedAt?: number | null;
}

export const reportDispute = (
  session: ServerSession,
  matchId: string,
  reason: string
): Promise<{ ok: boolean; matchId: string; disputeId: string; status: string }> =>
  request<{ ok: boolean; matchId: string; disputeId: string; status: string }>(
    "/api/dispute",
    { matchId, reason },
    session
  );

/**
 * What happened to my report (audit L-09).
 *
 * The report used to be fire-and-forget: `ok: true` and silence. A player who
 * asked "did anyone look at this?" had no way to find out, and an operator's
 * decision was invisible to the person who filed it.
 */
export const fetchDisputeStatus = (
  session: ServerSession,
  matchId: string
): Promise<{ matchId: string; count: number; disputes: DisputeReport[] }> =>
  request<{ matchId: string; count: number; disputes: DisputeReport[] }>(
    `/api/dispute/${encodeURIComponent(matchId)}`,
    undefined,
    session,
    "GET"
  );

export const commitRound = (
  session: ServerSession,
  matchId: string,
  roundIndex: number,
  intentHash: string
): Promise<{ ok: boolean }> => request("/api/round/commit", { matchId, roundIndex, intentHash }, session);

export interface RevealTarget {
  targetMs: number;
  proof: string;
  /** P0-fix (audit #2): per-player proof that MUST accompany the result submission. */
  resultProof: string;
  deadline: number;
}

export const revealRoundTarget = (
  session: ServerSession,
  matchId: string,
  roundIndex: number
): Promise<RevealTarget> => request("/api/round/target", { matchId, roundIndex }, session);

export interface SubmitResult {
  accepted: boolean;
  reason?: string;
}

export const submitRoundResult = (
  session: ServerSession,
  matchId: string,
  roundIndex: number,
  measuredMs: number,
  resultProof?: string,
  rttMs?: number
): Promise<SubmitResult> =>
  // Audit H1: `rttMs` lets the server compensate the reaction it observed for
  // network distance. Without it the ranking is `observed`, which latency can
  // only inflate — so the player nearer the server wins ties they did not earn.
  request("/api/round/result", { matchId, roundIndex, measuredMs, resultProof, rttMs }, session);

/**
 * Measure the round trip to the game server (audit H1).
 *
 * The server keeps the MINIMUM across the match, so an inflated report buys
 * nothing and a deflated one only reduces the player's own compensation. This
 * is a best-effort measurement: a failure returns `undefined` and the round is
 * submitted uncompensated rather than not at all.
 */
/**
 * Measure the player's round trip to the game server (audit H-03).
 *
 * The probe targets `/api/ping`, which does NO store, chain or RPC work. It used
 * to hit `/api/health`, whose payload includes the RPC reachability check — so
 * the "network latency" being compared against a 400ms cap also contained the
 * operator's chain I/O, and a player on a perfect connection could be refused
 * because the server's RPC was slow.
 *
 * Three samples, minimum taken: a single sample measures the worst moment of
 * the connection (TCP/TLS setup, a GC pause), and the cap decides whether
 * someone may play for money. The minimum is the closest estimate of the
 * path's real latency, and the client cannot gain by under-reporting — the
 * ranking uses the server-observed reaction, never this number.
 */
export const measureServerRttMs = async (session: ServerSession): Promise<number | undefined> => {
  if (!gameServerConfigured()) return undefined;
  const samples: number[] = [];
  for (let i = 0; i < 3; i += 1) {
    try {
      const started = performance.now();
      const res = await fetch(`${SERVER_URL}/api/ping`, {
        method: "GET",
        headers: { Authorization: `Bearer ${session.token}` },
        cache: "no-store",
      });
      if (!res.ok) return undefined;
      await res.json();
      samples.push(performance.now() - started);
    } catch {
      return undefined;
    }
  }
  if (samples.length === 0) return undefined;
  return Math.round(Math.min(...samples));
};

export interface SettledMatch {
  matchId: string;
  status: "settled" | "void";
  winner: string;
  winnerTimeMs: number;
  loserTimeMs: number;
  serverNonce: number;
  deadline: number;
  oracleAddress: string;
  signature: string;
  roundWins?: Record<string, number>;
  validatedTimes: Record<string, number[]>;
}

/** Ask the server to settle; returns the oracle-signed settlement. */
export const settleMatch = (session: ServerSession, matchId: string): Promise<SettledMatch> =>
  request<SettledMatch>(`/api/match/${encodeURIComponent(matchId)}/settle`, {}, session);

export interface ClaimResult {
  ok: boolean;
  onChainProof: boolean;
  reason?: string;
}

/** Persist a mined settlement only after the server verifies its receipt. */
export const claimMatch = (
  session: ServerSession,
  matchId: string,
  txHash: string,
): Promise<ClaimResult> =>
  request<ClaimResult>(`/api/match/${encodeURIComponent(matchId)}/claim`, { txHash }, session);

// Audit #10 (item 8): username claims moved OFF the direct-Firestore path
// (anyone could write usernames/{name} with any address — rules could not
// prove ownership). The claim now runs server-side, authenticated by this
// caller's SIWE session, inside the server's idempotent transaction.
export const claimUsername = (session: ServerSession, username: string): Promise<{ ok: boolean; cleanTag?: string; alreadyOwned?: boolean; detail?: string }> =>
  request(`/api/username/claim`, { username }, session);

/** The caller's own profile (audit H-05, 2026-10-22). */
export interface PlayerProfile {
  address: string;
  playerId: string;
  savedFriends: string[];
  updatedAt?: number | null;
}

export const fetchProfile = (session: ServerSession): Promise<PlayerProfile> =>
  request<PlayerProfile>("/api/profile", undefined, session, "GET");

/** A public friend card (audit M-19) — five fields, never the ledger record. */
export interface PublicPlayer {
  address: string;
  playerId: string;
  level: number;
  wins: number;
  totalMatches: number;
}

/**
 * Search players by tag or address THROUGH THE SERVER (audit M-19).
 *
 * The client used to read `users/*` directly. That document is the settlement
 * ledger — wallet-linked counters, reaction averages, history — and it was
 * world-readable only so a friend card could render. The server now returns the
 * five fields a card needs; the collection is closed to clients.
 */
export const searchPlayers = (
  session: ServerSession,
  term: string
): Promise<{ players: PublicPlayer[]; reason?: string }> =>
  request<{ players: PublicPlayer[]; reason?: string }>(
    `/api/players/search?q=${encodeURIComponent(term)}`,
    undefined,
    session,
    "GET"
  );

/** A podium row (audit M-04) — display fields only, never the ledger record. */
export interface LeaderboardRow {
  address: string;
  playerId?: string;
  wins: number;
  totalMatches: number;
  earnedUSDT: number;
  bestReactionMs: number;
  xp: number;
  level: number;
}

/**
 * The public leaderboard, through the server.
 *
 * No session: the podium is shown to visitors deciding whether to sign up, and
 * it contains nothing but a display row. The server caches it for 15 seconds.
 */
export const fetchLeaderboard = async (
  limit = 20
): Promise<{ players: LeaderboardRow[]; reason?: string }> => {
  if (!gameServerConfigured()) return { players: [], reason: "no game server configured" };
  const capped = Math.max(1, Math.min(limit, 50));
  const res = await fetch(`${SERVER_URL}/api/leaderboard?limit=${capped}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`leaderboard answered ${res.status}`);
  const body = (await res.json()) as { players?: LeaderboardRow[]; reason?: string };
  return { players: Array.isArray(body.players) ? body.players : [], reason: body.reason };
};

/**
 * Save a profile change. Omitted fields are left alone; `playerId: ""` clears
 * the display tag. Throws on 4xx so the caller can show the reason — a silent
 * failure here is what made saved friends disappear (audit H-05).
 */
export const saveProfile = (
  session: ServerSession,
  patch: { playerId?: string | null; savedFriends?: string[] }
): Promise<PlayerProfile> => request<PlayerProfile>("/api/profile", patch, session, "PUT");

/**
 * Convert a free-form server match id to the bytes32 the escrow contract uses.
 * MUST stay identical to api/oracle.py:_match_id_bytes32 (SHA-256 of the string).
 */
export const matchIdToBytes32 = async (matchId: string): Promise<string> => {
  const data = new TextEncoder().encode(matchId);
  // Audit M38: `crypto.subtle` exists ONLY in a secure context — HTTPS or
  // localhost. On a plain-HTTP deployment it is undefined, so this threw and
  // took the WHOLE on-chain deposit flow with it: no duel could be created or
  // joined, and the player saw an opaque "cannot read property of undefined".
  //
  // The hash is a pure function of the match id and must not depend on the
  // page's transport security. See `./sha256` for why this is a local
  // implementation rather than `ethers.sha256`.
  if (typeof crypto !== "undefined" && crypto.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", data);
    return (
      "0x" + Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("")
    );
  }
  return sha256Hex(data);
};

// --- Health -------------------------------------------------------------------

export interface ServerHealth {
  ok: boolean;
  service: string;
  rounds: number;
}

/** Cheap health probe used by the lobby to show an honest server status. */
export const probeServerHealth = async (): Promise<ServerHealth | null> => {
  if (!gameServerConfigured()) return null;
  try {
    const res = await fetch(`${SERVER_URL}/api/health`, { method: "GET" });
    if (!res.ok) return null;
    return (await res.json()) as ServerHealth;
  } catch {
    return null;
  }
};

export { SERVER_URL };
