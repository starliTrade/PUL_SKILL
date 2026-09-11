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

const SERVER_URL: string = (
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_GAME_SERVER_URL || ""
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
    // Server sessions expire after 24h; treat anything older than 23h as stale.
    if (Date.now() - s.issuedAt > 23 * 60 * 60 * 1000) return null;
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
  const { nonce, message } = (await nonceRes.json()) as { nonce: string; message: string };

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

// --- Authenticated request helper -------------------------------------------

const request = async <T>(
  path: string,
  body: unknown,
  session: ServerSession
): Promise<T> => {
  const res = await fetch(`${SERVER_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.token}`,
    },
    body: JSON.stringify(body ?? {}),
  });
  if (res.status === 401) {
    clearServerSession();
    throw new Error("Your game-server session expired. Please sign in again.");
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
  myRounds: {
    index: number;
    committed: boolean;
    targetRevealed: boolean;
    submitted: boolean;
    valid: boolean;
    rejectReason: string;
  }[];
}

/** Enter the matchmaking queue for a stake. Resolves when paired (server side). */
export const queueForMatch = (session: ServerSession, stake: number): Promise<MatchView> =>
  request<MatchView>("/api/queue", { stake }, session);

export const getMatch = (session: ServerSession, matchId: string): Promise<MatchView> =>
  request<MatchView>(`/api/match/${encodeURIComponent(matchId)}`, {}, session);

export const commitRound = (
  session: ServerSession,
  matchId: string,
  roundIndex: number,
  intentHash: string
): Promise<{ ok: boolean }> => request("/api/round/commit", { matchId, roundIndex, intentHash }, session);

export interface RevealTarget {
  targetMs: number;
  proof: string;
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
  measuredMs: number
): Promise<SubmitResult> => request("/api/round/result", { matchId, roundIndex, measuredMs }, session);

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

/**
 * Convert a free-form server match id to the bytes32 the escrow contract uses.
 * MUST stay identical to api/oracle.py:_match_id_bytes32 (SHA-256 of the string).
 */
export const matchIdToBytes32 = async (matchId: string): Promise<string> => {
  const data = new TextEncoder().encode(matchId);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return (
    "0x" + Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("")
  );
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
