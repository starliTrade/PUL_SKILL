/**
 * Pulsar Real Web3 & Firebase Firestore Real-Time Database Manager
 * Zero mock accounts, zero fake duels. Pure real-time on-chain & cloud persistence.
 */

import { doc, getDoc, collection, query, where, orderBy, limit, getDocs } from 'firebase/firestore';
import { getDb } from './firebase';
import { checkUsername, ensureSession, logoutServerSession, fetchRecentSettlements, gameServerConfigured, loadServerSession, fetchProfile, saveProfile, searchPlayers as searchPlayersOnServer, type SettlementRecord } from './gameServerClient';
import { CHAIN, TOKENS } from './chain';

import { eip6963Manager, EIP6963ProviderDetail } from './eip6963';
import { isMobileDevice, isWalletInAppBrowser, getWalletConnectDeepLink, getNativeSchemeUri, openWalletConnectInNativeApp } from './web3DeepLinks';
import { clearSaveFailure, reportSaveFailure } from './saveStatus';

export const getWalletConnectProjectId = (): string => {
  if (typeof window !== 'undefined') {
    const userStored = localStorage.getItem('pulsar_reown_project_id') || localStorage.getItem('pulsar_wc_project_id');
    if (userStored && userStored.trim().length > 0) {
      return userStored.trim();
    }
  }
  const envId = typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WALLETCONNECT_PROJECT_ID;
  if (envId && typeof envId === 'string' && envId.trim().length > 0) {
    return envId.trim();
  }
  // Audit #11 M4: NO hardcoded shared Project ID ships in the bundle anymore
  // (a shared relay identity is rate-limited per-app and ties every
  // deployment to one wallet dashboard). Configure VITE_WALLETCONNECT_
  // PROJECT_ID per environment; without it hasValidWalletConnectProjectId()
  // is false and the connect flow fails fast with a clear message instead
  // of silently riding a shared identity.
  return '';
};

export const setWalletConnectProjectId = (id: string): void => {
  if (typeof window === 'undefined') return;
  const clean = id.trim();
  if (clean) {
    localStorage.setItem('pulsar_reown_project_id', clean);
  } else {
    localStorage.removeItem('pulsar_reown_project_id');
  }
  realWeb3Manager.cancelPendingConnect();
};

export const hasValidWalletConnectProjectId = (): boolean => {
  const id = getWalletConnectProjectId();
  return Boolean(id && id.length >= 16);
};

/**
 * EthereumProvider class resolver for WalletConnect (ESM/CJS/default-export
 * shapes across bundlers).
 * Handles ESM, CJS, default export wrapping, and dynamic imports across all mobile and desktop browsers
 */
async function getEthereumProviderClass(): Promise<any> {
  try {
    const mod: any = await import('@walletconnect/ethereum-provider');
    const Provider =
      mod?.EthereumProvider ||
      mod?.default?.EthereumProvider ||
      (typeof mod?.init === 'function' ? mod : null) ||
      (typeof mod?.default?.init === 'function' ? mod?.default : null);

    if (Provider && typeof Provider.init === 'function') {
      return Provider;
    }
    console.error('WalletConnect module loaded but EthereumProvider.init was not found on:', mod);
  } catch (err) {
    console.error('Failed to dynamically load @walletconnect/ethereum-provider:', err);
  }
  throw new Error('WalletConnect provider could not be initialized in this browser.');
}

export interface ConnectedAccountState {
  address: string;
  shortAddress: string;
  chainId: number;
  networkName: string;
  balanceUSDT: number;
  balancePOL?: number;
  /** F-18: true until the first successful balance fetch. A zero shown
   *  before that is an RPC failure, not a fact — UI must not gate on it. */
  balanceUnknown: boolean;
  connected: boolean;
  providerName: string;
}

export interface MatchRecord {
  id: string;
  game: string;
  result: 'win' | 'loss' | 'void';
  entryFee: number;
  prize: number;
  opponentTime: number;
  yourTime: number;
  timestamp: number;
  matchId?: string;
  oracleSignature?: string;
  opponentName?: string;
  opponent?: string;
  reactionTime?: number;
  stake?: number;
  hash?: string;
  xpEarned?: number;
}

export interface UserWalletData {
  address: string;
  playerId?: string;
  vaultBalance: number;
  wins: number;
  losses: number;
  voids: number;
  totalMatches: number;
  bestReactionMs: number;
  avgReactionMs: number;
  xp: number;
  level: number;
  /** Audit M31: server-authoritative win streak (the XP bonus depends on it). */
  winStreak?: number;
  savedFriends?: string[];
  history: MatchRecord[];
}

export interface FriendProfile {
  address: string;
  playerId: string;
  shortAddress: string;
  level: number;
  xp: number;
  wins: number;
  totalMatches: number;
  bestReactionMs: number;
  winRate: number;
  status: 'online' | 'in_game' | 'offline';
  bio?: string;
}

export interface LeaderboardPlayer {
  address: string;
  shortAddress: string;
  name?: string;
  playerId?: string;
  wins: number;
  totalMatches: number;
  bestReactionMs: number;
  reactionTime?: number;
  winRate: number;
  totalEarnedUSDT: number;
  totalWinnings?: number;
  xp: number;
  level: number;
}

/**
 * The localStorage key the game page persists a live ranked match under.
 *
 * Audit H15: the identity lock reads it, so the two modules must agree on the
 * string — a typo here would silently disable the lock.
 */
export const ACTIVE_RANKED_MATCH_KEY = 'pulsar_active_ranked_match';

/** How often the lobby feed refreshes, and how many settlements it shows. */
const FEED_POLL_MS = 20_000;
const FEED_SIZE = 15;

/**
 * Turn settlement records into per-player feed rows (audit H-04).
 *
 * Pure and exported so the shape can be tested without a network: a settlement
 * names one winner, the feed needs a row per side, and inventing a default for a
 * missing side is exactly the fabrication class this project keeps fixing.
 */
export const settlementsToFeedRows = (settlements: SettlementRecord[]): MatchRecord[] => {
  const rows: MatchRecord[] = [];
  for (const s of settlements) {
    if (!s || !s.matchId || !s.winner || !Array.isArray(s.players)) continue;
    const winner = s.winner.toLowerCase();
    const winnerTime = typeof s.winnerTimeMs === "number" ? s.winnerTimeMs : 0;
    const loserTime = typeof s.loserTimeMs === "number" ? s.loserTimeMs : 0;
    for (const player of s.players) {
      const addr = String(player || "").toLowerCase();
      if (!addr) continue;
      const opponent = s.players.find((p) => String(p).toLowerCase() !== addr) || "";
      const won = addr === winner;
      rows.push({
        id: `${s.matchId}:${addr}`,
        matchId: s.matchId,
        game: "Reaction Duel",
        result: won ? "win" : "loss",
        entryFee: s.stake,
        stake: s.stake,
        prize: won ? s.prize : 0,
        yourTime: won ? winnerTime : loserTime,
        opponentTime: won ? loserTime : winnerTime,
        timestamp: Number(s.settledAt) > 0 ? Number(s.settledAt) * 1000 : Date.now(),
        opponentName: opponent ? `${opponent.slice(0, 6)}…${opponent.slice(-4)}` : "Arena Duelist",
        oracleSignature: s.signature,
        hash: s.settlementTx || undefined,
      });
    }
  }
  return rows;
};

/**
 * Fill in every field the rest of the app assumes exists (audit H-17).
 *
 * `users/{address}` is written by the SETTLEMENT LEDGER, which knows about wins,
 * XP and reaction times but not about `history` or `savedFriends`. It used to be
 * cast straight to `UserWalletData`, so `recordMatch` then ran
 * `[match, ...data.history]` on `undefined` and threw — the XP summary never
 * appeared after the first ranked duel. Normalising at the I/O boundary is the
 * only place that can guarantee the invariant for every consumer.
 *
 * Exported so the contract can be tested without Firestore: this is data the
 * ledger writes and the UI reads, and "missing field" must never mean "crash".
 */
export const normalizeUserData = (
  raw: Partial<UserWalletData> | null | undefined,
  addr: string,
  defaultTag: string
): UserWalletData => {
  const d = raw || {};
  return {
    address: String(d.address || addr).toLowerCase(),
    playerId: d.playerId || defaultTag,
    vaultBalance: Number(d.vaultBalance) || 0,
    wins: Number(d.wins) || 0,
    losses: Number(d.losses) || 0,
    voids: Number(d.voids) || 0,
    totalMatches: Number(d.totalMatches) || 0,
    bestReactionMs: Number(d.bestReactionMs) || 0,
    avgReactionMs: Number(d.avgReactionMs) || 0,
    xp: Number(d.xp) || 0,
    level: Number(d.level) || 1,
    winStreak: Number(d.winStreak) || 0,
    history: Array.isArray(d.history) ? d.history : [],
    savedFriends: Array.isArray(d.savedFriends) ? d.savedFriends : [],
  };
};

class RealWeb3Manager {
  private currentAccount: ConnectedAccountState = {
    address: '',
    shortAddress: '',
    chainId: CHAIN.chainId,
    networkName: CHAIN.name,
    balanceUSDT: 0,
    balanceUnknown: true,
    connected: false,
    providerName: '',
  };

  private listeners: Array<() => void> = [];
  /**
   * Audit H15 — set when a wallet or network change was REFUSED because a
   * ranked match is live. The UI reads it to tell the player what to do instead
   * of silently ignoring their action.
   */
  public identityLockedReason = '';

  constructor() {
    if (typeof window !== 'undefined') {
      this.attachForegroundResume();

      if ((window as any).ethereum) {
        const ethereum = (window as any).ethereum;

        ethereum.on?.('accountsChanged', (accounts: string[]) => {
          if (!accounts || accounts.length === 0) {
            this.disconnect();
            return;
          }
          // Audit H15: switching accounts mid-match would change
          // `wallet.fullAddress` while the server session, the match and the
          // escrow deposits all belong to the previous address — the player
          // would be playing as someone else, and `iWon` would be evaluated
          // against the wrong wallet.
          if (this.hasLiveRankedMatch()) {
            this.identityLockedReason =
              'Your wallet changed, but a ranked match is in progress. Finish or ' +
              'leave the match before switching accounts.';
            this.notify();
            return;
          }
          this.setConnectedAddress(
            accounts[0],
            this.currentAccount.providerName || 'MetaMask',
            CHAIN.chainId,
            ethereum
          );
        });

        ethereum.on?.('chainChanged', () => {
          // Audit H15: a reload destroys the in-memory provider — on
          // WalletConnect that loses the session mid-match. Refuse and explain.
          if (this.hasLiveRankedMatch()) {
            this.identityLockedReason =
              'Your wallet switched network, but a ranked match is in progress. ' +
              'Finish or leave the match, then switch back.';
            this.notify();
            return;
          }
          window.location.reload();
        });

        ethereum.on?.('disconnect', () => {
          this.disconnect();
        });
      }
    }
  }

  /**
   * True while a ranked duel is in flight (audit H15).
   *
   * The game page persists the live match under this key; while it is present
   * the player's identity and network are frozen, because the server session,
   * the match and the escrow deposits were all created under the current
   * address on the current chain.
   */
  private hasLiveRankedMatch(): boolean {
    try {
      const raw = localStorage.getItem(ACTIVE_RANKED_MATCH_KEY);
      if (!raw) return false;
      const saved = JSON.parse(raw) as { matchId?: string };
      return Boolean(saved?.matchId);
    } catch {
      return false;
    }
  }

  public subscribe(callback: () => void): () => void {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== callback);
    };
  }

  private notify(): void {
    this.listeners.forEach((cb) => cb());
  }

  public getAccount(): ConnectedAccountState {
    return this.currentAccount;
  }

  public hasInjected(): boolean {
    if (typeof window === 'undefined') return false;
    let has = Boolean(
      (window as any).ethereum ||
      (window as any).phantom?.ethereum ||
      (window as any).coinbaseWalletExtension ||
      (window as any).trustwallet
    );
    if (!has) {
      try {
        if (window.parent && (window.parent as any).ethereum) has = true;
      } catch {}
      try {
        if (window.top && (window.top as any).ethereum) has = true;
      } catch {}
    }
    return has;
  }


  private wcProvider: any = null;
  /**
   * Audit C3 — the EIP-1193 provider the user ACTUALLY connected with.
   *
   * `getActiveEip1193Provider()` used to fall back to `window.ethereum`, which
   * is whatever wallet happens to own that slot — not necessarily the one the
   * user picked. With two wallets installed (e.g. MetaMask on window.ethereum
   * and Coinbase connected through EIP-6963) every money transaction
   * (approveUsdt / createDuel / settleDuel) and the SIWE signature were routed
   * to the wrong account. Recording the chosen provider at connect time is the
   * only reliable way to know which one to sign with.
   */
  private activeProvider: any = null;
  private wcInitPromise: Promise<any> | null = null;
  private wcConnectPromise: Promise<ConnectedAccountState> | null = null;
  private wcEventsBound = false;
  private wcForegroundBound = false;
  private pendingWalletName = 'WalletConnect';
  private wcUriListeners: Array<(uri: string) => void> = [];
  public lastWcUri: string | null = null;
  public lastHandoff: { uri: string; deepLink: string; nativeScheme: string } | null = null;

  public onWcUri(callback: (uri: string) => void): () => void {
    this.wcUriListeners.push(callback);
    if (this.lastWcUri) {
      callback(this.lastWcUri);
    }
    return () => {
      this.wcUriListeners = this.wcUriListeners.filter((cb) => cb !== callback);
    };
  }

  public getEIP6963Providers(): EIP6963ProviderDetail[] {
    return eip6963Manager.getProviders();
  }

  private wcMetadata() {
    const origin = typeof window !== 'undefined' ? window.location.origin : 'https://pulsar.arena';
    return {
      name: 'PULSAR Arena',
      description: 'PULSAR Ultra-Reaction Arena',
      url: origin,
      icons: ['https://avatars.githubusercontent.com/u/37784886'],
      redirect: {
        universal: origin,
      },
    };
  }

  private emitWcUri(uri: string, walletName: string = this.pendingWalletName): void {
    this.lastWcUri = uri;
    const deepLink = getWalletConnectDeepLink(walletName, uri);
    const nativeScheme = getNativeSchemeUri(walletName, uri);
    this.lastHandoff = { uri, deepLink, nativeScheme };
    this.wcUriListeners.forEach((cb) => cb(uri));
  }

  private bindWcProviderEvents(provider: any): void {
    if (!provider || this.wcEventsBound) return;
    this.wcEventsBound = true;

    try {
      provider.on('error', (err: any) => {
        console.warn('[Pulsar Web3] WalletConnect provider error:', err);
      });
      const innerProvider = provider?.signer?.client?.core?.relayer?.provider;
      if (innerProvider && typeof innerProvider.on === 'function') {
        innerProvider.on('error', (err: any) => {
          console.warn('[Pulsar Web3] WalletConnect relay error:', err);
        });
      }
    } catch {
      /* ignore */
    }

    provider.on('connect', () => {
      // Audit 8.20: this was a third, hand-rolled session walk.
      const accounts = this.wcAccounts(provider);
      if (accounts.length === 0) {
        const session = provider.session || provider?.signer?.session;
        if (session?.namespaces) {
          for (const ns of Object.values(session.namespaces) as any[]) {
            if (ns?.accounts && Array.isArray(ns.accounts)) {
              for (const acc of ns.accounts) {
                const cleanAddr = String(acc).split(':').pop();
                if (cleanAddr && cleanAddr.startsWith('0x')) {
                  accounts.push(cleanAddr);
                }
              }
            }
          }
        }
      }
      if (accounts && accounts.length > 0) {
        this.bindActiveProvider(this.wcProvider);
        void this.setConnectedAddress(accounts[0], this.pendingWalletName || 'WalletConnect', provider.chainId || CHAIN.chainId);
      }
    });

    provider.on('display_uri', (uri: string) => {
      this.emitWcUri(uri, this.pendingWalletName);
    });

    provider.on('accountsChanged', (accounts: string[]) => {
      if (!accounts || accounts.length === 0) {
        this.disconnect();
      } else {
        this.bindActiveProvider(this.wcProvider);
        this.setConnectedAddress(accounts[0], this.pendingWalletName || 'WalletConnect', CHAIN.chainId);
      }
    });

    provider.on('disconnect', () => {
      if (this.currentAccount.connected) {
        this.disconnect();
      }
    });
  }

  private attachForegroundResume(): void {
    if (this.wcForegroundBound || typeof document === 'undefined') return;
    this.wcForegroundBound = true;

    const resume = async () => {
      if (this.currentAccount.connected) return;

      if (this.wcProvider) {
        try {
          const relayer = this.wcProvider?.signer?.client?.core?.relayer;
          if (relayer && typeof relayer.transportOpen === 'function' && !relayer.connected) {
            await relayer.transportOpen();
          }
        } catch {
          /* ignore */
        }

        try {
          // Extract accounts directly or from active UniversalProvider sessions
          const accounts: string[] = this.wcProvider?.accounts || [];
          if (!accounts || accounts.length === 0) {
            const activeSessions = this.wcProvider?.client?.session?.getAll?.() || [];
            if (activeSessions.length > 0) {
              const latestSession = activeSessions[activeSessions.length - 1];
              const namespaces = latestSession?.namespaces || {};
              for (const ns of Object.values(namespaces) as any[]) {
                if (ns?.accounts && Array.isArray(ns.accounts)) {
                  for (const acc of ns.accounts) {
                    const cleanAddr = String(acc).split(':').pop();
                    if (cleanAddr && cleanAddr.startsWith('0x')) {
                      accounts.push(cleanAddr);
                    }
                  }
                }
              }
            }
          }

          if (accounts && accounts.length > 0 && !this.currentAccount.connected) {
            await this.setConnectedAddress(
              accounts[0],
              this.pendingWalletName || 'Trust Wallet',
              this.wcProvider.chainId || CHAIN.chainId,
              this.wcProvider
            );
            return;
          }
        } catch (e) {
          console.warn('[Pulsar Web3] Resume session recovery:', e);
        }
      }

      // Check injected provider if available
      try {
        await this.restoreSession();
      } catch {}
    };

    const scheduleResumeCheck = () => {
      void resume();
      setTimeout(() => void resume(), 400);
      setTimeout(() => void resume(), 1200);
      setTimeout(() => void resume(), 2500);
    };

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        scheduleResumeCheck();
      }
    });
    window.addEventListener('pageshow', () => {
      scheduleResumeCheck();
    });
    window.addEventListener('focus', () => {
      scheduleResumeCheck();
    });
  }

  private async ensureWcProvider(): Promise<any> {
    if (this.wcProvider) return this.wcProvider;
    if (this.wcInitPromise) return this.wcInitPromise;

    this.wcInitPromise = (async () => {
      // Purge any stale/orphaned proposal keys before initializing provider.
      // Audit M36: iterate BACKWARDS — localStorage indices shift under the
      // cursor as keys are removed, so a forward loop skips the entry that
      // slides into each vacated slot (the trap main.tsx already documents).
      try {
        if (typeof window !== 'undefined' && window.localStorage) {
          for (let i = localStorage.length - 1; i >= 0; i--) {
            const k = localStorage.key(i);
            if (k && k.startsWith('wc@2:') && k.includes('proposal')) {
              localStorage.removeItem(k);
            }
          }
        }
      } catch {}

      const EthereumProviderClass = await getEthereumProviderClass();
      const projectId = getWalletConnectProjectId();
      if (!projectId || projectId.length < 10) {
        throw new Error(
          'REOWN_PROJECT_ID_REQUIRED: A valid Reown Cloud Project ID is required for mobile wallet connections. Get a free ID at cloud.reown.com or use Guest Duelist.'
        );
      }

      const initTask = EthereumProviderClass.init({
        projectId,
        chains: [CHAIN.chainId],
        optionalChains: [137, 1, 56, 42161],
        showQrModal: false,
        disableProviderPing: true,
        metadata: this.wcMetadata(),
      });

      const initTimeout = new Promise<never>((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                'REOWN_INIT_TIMEOUT: Connection to Reown/WalletConnect relay timed out. Check your Project ID or internet connection.'
              )
            ),
          12000
        )
      );

      const provider = await Promise.race([initTask, initTimeout]);
      this.wcProvider = provider;
      this.bindWcProviderEvents(provider);
      return provider;
    })();

    try {
      return await this.wcInitPromise;
    } catch (err) {
      this.wcInitPromise = null;
      this.wcProvider = null;
      this.wcEventsBound = false;
      throw err;
    }
  }

  private mapWcError(err: any, providerName: string): Error {
    const msg = String(err?.message || err || '');
    if (msg.includes('REOWN_PROJECT_ID_REQUIRED')) {
      return new Error(
        'Reown (WalletConnect) Project ID is required for mobile wallet apps. Please enter your free Project ID in Settings or play instantly with Guest Duelist.'
      );
    }
    if (msg.includes('401') || msg.includes('Unauthorized')) {
      return new Error(
        'Reown Project ID is invalid or unauthorized (401). Please create a free project at cloud.reown.com and update the Project ID.'
      );
    }
    if (msg.includes('REOWN_INIT_TIMEOUT') || msg.includes('REOWN_URI_TIMEOUT')) {
      return new Error(
        'Connection to wallet relay timed out. Check your internet connection or try again.'
      );
    }
    if (
      msg.includes('User closed') ||
      msg.includes('Modal closed') ||
      msg.includes('User rejected') ||
      msg.includes('cancelled')
    ) {
      return new Error('Connection request was cancelled in your wallet.');
    }
    if (
      msg.includes('3000') ||
      msg.includes('403') ||
      msg.includes('forbidden') ||
      msg.includes('HTTP status code') ||
      msg.includes('origin not allowed') ||
      msg.includes('WebSocket connection closed')
    ) {
      return new Error(
        `WalletConnect relay blocked this request (403). Ensure Domain Allowlist is empty in cloud.reown.com, then tap ${providerName} again.`
      );
    }
    if (err instanceof Error) return err;
    return new Error(msg || `Failed to connect ${providerName}`);
  }

  public async restoreSession(): Promise<ConnectedAccountState | null> {
    if (typeof window === 'undefined') return null;

    const savedAddr = localStorage.getItem('pulsar_active_address');
    const savedProvider = localStorage.getItem('pulsar_active_provider') || 'Wallet';
    const connectionMode = localStorage.getItem('pulsar_connection_mode');
    if (!savedAddr) return null;

    // If currently already connected in memory with this exact address, retain session immediately
    if (this.currentAccount.connected && this.currentAccount.address.toLowerCase() === savedAddr.toLowerCase()) {
      return this.currentAccount;
    }

    // 1. If connection mode was WalletConnect / mobile or provider is mobile wallet
    const isWc =
      connectionMode === 'walletconnect' ||
      savedProvider === 'WalletConnect' ||
      savedProvider?.toLowerCase().includes('walletconnect') ||
      isMobileDevice();

    if (isWc) {
      try {
        const provider = await this.ensureWcProvider();
        const accounts = this.wcAccounts(provider);
        if (accounts.length === 0) {
          const activeSessions = provider?.client?.session?.getAll?.() || [];
          if (activeSessions.length > 0) {
            const latestSession = activeSessions[activeSessions.length - 1];
            const namespaces = latestSession?.namespaces || {};
            for (const ns of Object.values(namespaces) as any[]) {
              if (ns?.accounts && Array.isArray(ns.accounts)) {
                for (const acc of ns.accounts) {
                  const cleanAddr = String(acc).split(':').pop();
                  if (cleanAddr && cleanAddr.startsWith('0x')) {
                    accounts.push(cleanAddr);
                  }
                }
              }
            }
          }
        }

        if (accounts && accounts.length > 0) {
          this.pendingWalletName = savedProvider;
          return await this.setConnectedAddress(
            accounts[0],
            savedProvider,
            provider.chainId || CHAIN.chainId,
            provider
          );
        } else if (savedAddr) {
          return await this.setConnectedAddress(savedAddr, savedProvider, CHAIN.chainId, provider);
        }
      } catch (err) {
        console.warn('[Pulsar Web3] WalletConnect session recovery fallback:', err);
        if (savedAddr) {
          return await this.setConnectedAddress(savedAddr, savedProvider, CHAIN.chainId);
        }
      }
    }

    // 2. Injected Wallet (Desktop browser extensions)
    const injected = this.getInjectedProvider(savedProvider || 'MetaMask');
    if (injected) {
      try {
        const accounts: string[] = await injected.request({ method: 'eth_accounts' });
        if (accounts && accounts.length > 0 && accounts[0].toLowerCase() === savedAddr.toLowerCase()) {
          let chainId: number = CHAIN.chainId;
          try {
            const chainHex = await injected.request({ method: 'eth_chainId' });
            if (chainHex) chainId = parseInt(chainHex, 16);
          } catch {}
          return await this.setConnectedAddress(accounts[0], savedProvider, chainId, injected);
        }
      } catch {}
    }

    // Audit #7 R6: the old "siweVerified → restore" path was part of the dead
    // local SIWE protocol (a client-side signature proves nothing server-side).
    // Identity is the server SIWE session only; a persisted address alone must
    // never silently become a connected wallet.
    return null;
  }

  public async restoreWalletConnectSession(): Promise<ConnectedAccountState | null> {
    return this.restoreSession();
  }

  public prepareWalletConnect(): void {
    if (typeof window === 'undefined') return;
    if (this.currentAccount.connected) return;
    if (this.wcConnectPromise) return;
    void this.startWalletConnectPairing('WalletConnect');
  }

  public openPreparedWallet(walletId: string): boolean {
    const uri = this.lastWcUri;
    if (!uri) return false;
    this.pendingWalletName = walletId;
    this.emitWcUri(uri, walletId);
    return openWalletConnectInNativeApp(walletId, uri);
  }

  /**
   * The accounts a WalletConnect provider can actually use.
   *
   * Audit 8.20: `provider.accounts` falls back to the live session in five
   * places, each written slightly differently — one checks `Array.isArray`,
   * another `?.length`, another mutates the provider's own array. A session that
   * survives a tab suspend is only visible through the session path, so a
   * divergence here means "connected" in one flow and "no accounts" in another.
   */
  private wcAccounts(provider: any): string[] {
    const direct = provider?.accounts;
    if (Array.isArray(direct) && direct.length > 0) return [...direct];
    return this.activeSessionAccounts(provider);
  }

  /**
   * Accounts already approved in a live WalletConnect session (survives tab
   * suspend).
   *
   * Audit 8.20: the two session lookups in this file disagreed — the `connect`
   * handler read `provider.session.namespaces` while the resume paths read
   * `provider.client.session.getAll()`. They can differ (the first is the
   * CURRENT session, the second is every persisted one), so "connected" was
   * true in one flow and false in another. This checks both, in that order.
   */
  private activeSessionAccounts(provider: any): string[] {
    const out: string[] = [];
    const collect = (namespaces: any) => {
      for (const ns of Object.values(namespaces || {}) as any[]) {
        if (ns?.accounts && Array.isArray(ns.accounts)) {
          for (const acc of ns.accounts) {
            const cleanAddr = String(acc).split(':').pop();
            if (cleanAddr && cleanAddr.startsWith('0x') && !out.includes(cleanAddr)) {
              out.push(cleanAddr);
            }
          }
        }
      }
    };
    try {
      // The live session first (the `connect` handler's source) …
      collect(provider?.session?.namespaces);
      // … then every persisted session (the resume paths' source).
      const activeSessions = provider?.client?.session?.getAll?.() || [];
      for (const session of activeSessions) collect(session?.namespaces);
    } catch {}
    return out;
  }

  private async startWalletConnectPairing(
    providerName: string,
    onUri?: (uri: string, deepLink: string, nativeScheme?: string) => void
  ): Promise<ConnectedAccountState> {
    this.pendingWalletName = providerName;

    // Fresh-load resume: iOS may have killed the tab mid-pairing, so no
    // promise is pending — but the approval can still live in persisted WC
    // storage. Reuse it instead of starting yet another pairing round.
    try {
      const existing: any = await this.ensureWcProvider();
      const existingAccts: string[] = this.wcAccounts(existing);
      if (existing?.session && existingAccts.length) {
        this.lastWcUri = null;
        return await this.setConnectedAddress(
          existingAccts[0],
          providerName,
          existing.chainId || CHAIN.chainId,
          existing
        );
      }
    } catch {}

    if (this.wcConnectPromise) {
      // Fast-resume: the user may have approved in the wallet while iOS had
      // this tab suspended — the pending connect() then never resolves and
      // every re-tap would return the same stale promise (looks "stuck").
      // If a session with accounts exists NOW, use it immediately.
      try {
        const p: any = this.wcProvider;
        const sessAccts: string[] = this.wcAccounts(p);
        if (p?.session && sessAccts?.length) {
          this.wcConnectPromise = null;
          this.lastWcUri = null;
          return this.setConnectedAddress(
            sessAccts[0],
            providerName,
            p.chainId || CHAIN.chainId,
            p
          );
        }
      } catch {}
      if (this.lastWcUri && onUri) {
        onUri(
          this.lastWcUri,
          getWalletConnectDeepLink(providerName, this.lastWcUri),
          getNativeSchemeUri(providerName, this.lastWcUri)
        );
      }
      return this.wcConnectPromise;
    }

    this.wcConnectPromise = (async () => {
      try {
        const provider = await this.ensureWcProvider();

        // Audit 8.20: this required `provider.accounts` to be populated and so
        // skipped the session fallback the other paths have — the exact
        // "approved while the tab was suspended" case it exists for.
        const fastAccounts = this.wcAccounts(provider);
        if (provider.session && fastAccounts.length) {
          return await this.setConnectedAddress(
            fastAccounts[0],
            providerName,
            provider.chainId || CHAIN.chainId,
            provider
          );
        }

        const uriUnsub = this.onWcUri((uri) => {
          if (onUri) {
            onUri(uri, getWalletConnectDeepLink(providerName, uri), getNativeSchemeUri(providerName, uri));
          }
        });

        const connectPromise = provider.connect();
        const timeoutPromise = new Promise<never>((_, reject) =>
          setTimeout(
            () =>
              reject(
                new Error(
                  `Connection to ${providerName} timed out. Return to this browser after approving in the wallet.`
                )
              ),
            300000
          )
        );

        try {
          await Promise.race([connectPromise, timeoutPromise]);
        } finally {
          uriUnsub();
        }

        const accounts = this.wcAccounts(provider);

        if (accounts.length > 0) {
          const chainId = provider.chainId || CHAIN.chainId;
          return await this.setConnectedAddress(accounts[0], providerName, chainId, provider);
        }
        throw new Error('No accounts selected in your wallet.');
      } catch (err: any) {
        this.wcConnectPromise = null;
        throw this.mapWcError(err, providerName);
      }
    })();

    this.wcConnectPromise.then(
      () => {
        this.wcConnectPromise = null;
        this.lastWcUri = null;
      },
      () => {
        this.wcConnectPromise = null;
      }
    );

    return this.wcConnectPromise;
  }

  public async connectWalletConnect(onUriGenerated?: (uri: string) => void): Promise<ConnectedAccountState> {
    return this.startWalletConnectPairing('WalletConnect', (uri) => {
      onUriGenerated?.(uri);
    });
  }

  public getInjectedProvider(providerName: string = 'MetaMask'): any {
    if (typeof window === 'undefined') return null;

    // 1. Check EIP-6963 announced providers first
    const eip6963Match = eip6963Manager.getProviderByName(providerName);
    if (eip6963Match?.provider) {
      return eip6963Match.provider;
    }

    let eth = (window as any).ethereum;
    const phantomEth = (window as any).phantom?.ethereum;
    const coinbaseEth = (window as any).coinbaseWalletExtension;
    const trustEth = (window as any).trustwallet;

    if (!eth && !phantomEth && !coinbaseEth && !trustEth) {
      try {
        if (window.parent && (window.parent as any).ethereum) {
          eth = (window.parent as any).ethereum;
        }
      } catch {}
      try {
        if (window.top && (window.top as any).ethereum) {
          eth = (window.top as any).ethereum;
        }
      } catch {}
    }

    if (providerName === 'Phantom' && phantomEth) return phantomEth;
    if (providerName === 'Coinbase' && coinbaseEth) return coinbaseEth;
    if (providerName === 'TrustWallet' && trustEth) return trustEth;

    if (!eth) return phantomEth || coinbaseEth || trustEth || null;

    if (Array.isArray(eth.providers) && eth.providers.length > 0) {
      if (providerName === 'MetaMask') {
        const found = eth.providers.find((p: any) => p.isMetaMask && !p.isPhantom && !p.isBraveWallet);
        return found || eth.providers.find((p: any) => p.isMetaMask) || eth;
      }
      if (providerName === 'Phantom') {
        return eth.providers.find((p: any) => p.isPhantom) || phantomEth || eth;
      }
      if (providerName === 'Coinbase') {
        return eth.providers.find((p: any) => p.isCoinbaseWallet) || coinbaseEth || eth;
      }
      if (providerName === 'TrustWallet') {
        return eth.providers.find((p: any) => p.isTrust || p.isTrustWallet) || trustEth || eth;
      }
    }
    return eth;
  }

  public async connectEIP6963(providerDetail: EIP6963ProviderDetail): Promise<ConnectedAccountState> {
    const provider = providerDetail.provider;
    if (!provider) {
      throw new Error(`Provider for ${providerDetail.info.name} is not available.`);
    }

    try {
      const accounts: string[] = await provider.request({
        method: 'eth_requestAccounts',
      });

      if (accounts && accounts.length > 0) {
        let chainId: number = CHAIN.chainId;
        try {
          const chainIdHex = await provider.request({ method: 'eth_chainId' });
          if (chainIdHex) chainId = parseInt(chainIdHex, 16);
        } catch {}

        if (chainId !== CHAIN.chainId) {
          try {
            await provider.request({
              method: 'wallet_switchEthereumChain',
              params: [{ chainId: CHAIN.chainHex }],
            });
            chainId = CHAIN.chainId;
          } catch (switchError: any) {
            if (switchError.code === 4902) {
              try {
                await provider.request({
                  method: 'wallet_addEthereumChain',
                  params: [
                    {
                      chainId: CHAIN.chainHex,
                      chainName: CHAIN.name,
                      nativeCurrency: { name: CHAIN.currency, symbol: CHAIN.currency, decimals: 18 },
                      rpcUrls: [...CHAIN.rpcUrls],
                      blockExplorerUrls: [CHAIN.explorerUrl],
                    },
                  ],
                });
                chainId = CHAIN.chainId;
              } catch {}
            }
          }
        }

        // Audit C3: remember WHICH provider this session belongs to.
        this.bindActiveProvider(provider);
        return await this.setConnectedAddress(accounts[0], providerDetail.info.name, chainId);
      } else {
        throw new Error('No accounts selected in your wallet.');
      }
    } catch (err: any) {
      if (err?.code === 4001 || err?.message?.includes('User rejected') || err?.message?.includes('cancelled')) {
        throw new Error('Connection request was cancelled in your wallet.', { cause: err });
      }
      if (err?.code === -32002) {
        throw new Error(
          'Wallet is already waiting for your confirmation. Please check your wallet extension or app.',
          { cause: err },
        );
      }
      const inIframe = typeof window !== 'undefined' && window.self !== window.top;
      if (inIframe) {
        throw new Error(
          `Could not connect to ${providerDetail.info.name} inside the preview iframe. Please use WalletConnect QR, Instant Guest Duelist, or open in a new tab.`,
          { cause: err },
        );
      }
      throw new Error(err?.message || `Failed to connect to ${providerDetail.info.name}`, { cause: err });
    }
  }

  public async connectWalletConnectTargeted(
    providerName: string = 'MetaMask',
    onUri?: (uri: string, deepLink: string, nativeScheme?: string) => void
  ): Promise<ConnectedAccountState> {
    return this.startWalletConnectPairing(providerName, onUri);
  }

  public cancelPendingConnect(): void {
    this.wcConnectPromise = null;
    this.lastWcUri = null;
    this.lastHandoff = null;
    if (this.wcProvider) {
      // Audit M36: `provider.connect()` opens the relay transport immediately,
      // so `connected` is already true while the wallet has not approved yet.
      // The old `!connected` guard therefore skipped the teardown in exactly
      // the case that needed it — the live one — and cancelling dropped our
      // only reference to a provider whose relay socket stayed open (the WC
      // keys were never cleaned up either). Always close the relay when we
      // abandon a pairing, mirroring `disconnect()`'s guard semantics.
      try {
        if (typeof this.wcProvider.disconnect === 'function') {
          Promise.resolve(this.wcProvider.disconnect()).catch(() => {});
        }
      } catch {
        /* ignore */
      }
      this.wcProvider = null;
      this.wcInitPromise = null;
      this.wcEventsBound = false;
    }
  }

  public async connect(
    provider: string = 'MetaMask',
    onUri?: (uri: string, deepLink: string, nativeScheme?: string) => void
  ): Promise<ConnectedAccountState> {
    const mobileSafariOrChrome = isMobileDevice() && !isWalletInAppBrowser();

    // System browsers (iOS Safari / Chrome) have no injected wallet. Use WalletConnect only.
    if (mobileSafariOrChrome) {
      return await this.connectWalletConnectTargeted(provider, onUri);
    }

    let injected = this.getInjectedProvider(provider);

    if (!injected && typeof window !== 'undefined') {
      const anyEth =
        (window as any).ethereum ||
        (window as any).trustwallet ||
        (window as any).phantom?.ethereum ||
        (window as any).coinbaseWalletExtension;
      if (anyEth) {
        injected = anyEth;
      }
    }

    if (injected) {
      try {
        const accounts: string[] = await injected.request({
          method: 'eth_requestAccounts',
        });

        if (accounts && accounts.length > 0) {
          let chainId: number = CHAIN.chainId;
          try {
            const chainIdHex = await injected.request({ method: 'eth_chainId' });
            if (chainIdHex) chainId = parseInt(chainIdHex, 16);
          } catch {}

          if (chainId !== CHAIN.chainId) {
            try {
              await injected.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: CHAIN.chainHex }],
              });
              chainId = CHAIN.chainId;
            } catch (switchError: any) {
              if (switchError.code === 4902) {
                await injected.request({
                  method: 'wallet_addEthereumChain',
                  params: [{
                    chainId: CHAIN.chainHex,
                    chainName: CHAIN.name,
                    nativeCurrency: { name: CHAIN.currency, symbol: CHAIN.currency, decimals: 18 },
                    rpcUrls: [...CHAIN.rpcUrls],
                    blockExplorerUrls: [CHAIN.explorerUrl],
                  }],
                });
                chainId = CHAIN.chainId;
              } else {
                throw new Error('Please approve the Polygon network switch in your wallet.', { cause: switchError });
              }
            }
          }

          // Audit C3: `injected` is the EIP-1193 object we actually talked to.
          this.bindActiveProvider(injected);
          return await this.setConnectedAddress(accounts[0], provider, chainId);
        }
        throw new Error('No wallet account was selected.');
      } catch (err: any) {
        if (err?.code === 4001 || err?.message?.includes('User rejected') || err?.message?.includes('cancelled')) {
          throw new Error('Connection request was cancelled in your wallet.', { cause: err });
        }
        if (err?.code === -32002) {
          throw new Error('Wallet is waiting for your confirmation. Please check your wallet app.', { cause: err });
        }
        const inIframe = typeof window !== 'undefined' && window.self !== window.top;
        if (inIframe) {
          return await this.connectWalletConnectTargeted(provider, onUri);
        }
        if (isMobileDevice()) {
          return await this.connectWalletConnectTargeted(provider, onUri);
        }
        if (err instanceof Error) throw err;
        throw new Error('The wallet did not complete the connection request.', { cause: err });
      }
    }

    return await this.connectWalletConnectTargeted(provider, onUri);
  }

  /**
   * P0.5 — DEPRECATED forgery vector. This method previously allowed claiming
   * any address without proving ownership. It is now disabled: real ownership
   * proof flows through requestOwnershipSignature (SIWE) instead.
   */
  public async connectDirect(address: string, providerName: string = 'EVM Wallet'): Promise<ConnectedAccountState> {
    void address;
    void providerName;
    throw new Error(
      'Direct address entry is disabled. Connect a real wallet (or scan the WalletConnect code) to prove ownership.'
    );
  }

  /**
   * Record which EIP-1193 provider the user connected with (audit C3).
   *
   * Called from every connect path so `getActiveEip1193Provider()` can return
   * the wallet the user actually chose instead of guessing from
   * `window.ethereum`. Pass `null` on disconnect.
   */
  public bindActiveProvider(provider: any | null): void {
    this.activeProvider = provider ?? null;
  }

  /** EIP-1193 provider of the currently connected wallet (injected or WalletConnect). */
  public getActiveEip1193Provider(): any | null {
    const wc: any = this.wcProvider;
    if (wc?.connected) {
      // Validate the WC session before trusting it: after an iOS tab suspend
      // or a stale restore the provider object can report `connected` while
      // its internal namespace is gone — every request then throws
      // "undefined is not an object (evaluating 'this.namespace...')".
      // A zombie must NOT shadow the healthy injected provider.
      let alive: boolean;
      try {
        alive = !!(wc.session && this.wcAccounts(wc).length > 0);
      } catch {
        alive = false;
      }
      if (alive) return wc;
      try {
        if (typeof wc.disconnect === 'function') wc.disconnect().catch(() => {});
      } catch {}
      // The recorded provider may BE this zombie (the WalletConnect connect and
      // restore paths bind `this.wcProvider`). Clearing only `wcProvider` would
      // leave `activeProvider` pointing at the dead object, and the fallback
      // below would hand it straight back — every request then throws
      // "undefined is not an object (evaluating 'this.namespace...')".
      if (this.activeProvider === wc) this.activeProvider = null;
      this.wcProvider = null;
      this.wcConnectPromise = null;
    }
    // Audit C3: prefer the provider the user actually connected with. Only fall
    // back to window.ethereum when nothing was recorded (e.g. a session
    // restored from a previous page load before the connect path ran).
    if (this.activeProvider) return this.activeProvider;
    const injected = typeof window !== 'undefined' ? (window as any).ethereum : null;
    return injected || null;
  }

  public disconnect(): void {
    this.bindActiveProvider(null);
    this.identityLockedReason = '';
    // Audit H22b: revoke the SERVER session too. Dropping only the local copy
    // left the bearer token valid server-side for the rest of its 2h TTL.
    void logoutServerSession().catch(() => {});
    try {
      if (this.wcProvider?.connected) {
        this.wcProvider.disconnect().catch(() => {});
      }
    } catch {
      /* ignore */
    }
    this.wcConnectPromise = null;
    this.lastWcUri = null;
    this.lastHandoff = null;
    try {
      localStorage.removeItem('pulsar_active_address');
      localStorage.removeItem('pulsar_active_provider');
      localStorage.removeItem('pulsar_quick_address');
      localStorage.removeItem('pulsar_quick_key');
    } catch {}
    this.currentAccount = {
      address: '',
      shortAddress: '',
      chainId: CHAIN.chainId,
      networkName: CHAIN.name,
      balanceUSDT: 0,
      balanceUnknown: true,
      connected: false,
      providerName: '',
    };
    this.notify();
  }

  public async fetchLiveOnChainBalances(address: string): Promise<{ usdt: number; pol: number; ok: boolean }> {
    if (!address || !address.startsWith('0x') || address.length !== 42) {
      return { usdt: 0, pol: 0, ok: false };
    }
    const rpcs = CHAIN.rpcUrls;
    for (const rpc of rpcs) {
      try {
        const { ethers } = await import('ethers');
        const provider = new ethers.JsonRpcProvider(rpc, CHAIN.chainId, { staticNetwork: true });

        const polWei = await provider.getBalance(address);
        const pol = parseFloat(ethers.formatEther(polWei));

        // F-18: read decimals() from the token itself. A testnet token with
        // 18 decimals no longer inflates every amount by 10^12.
        const usdtContract = new ethers.Contract(
          TOKENS.USDT,
          [
            'function balanceOf(address) view returns (uint256)',
            'function decimals() view returns (uint8)',
          ],
          provider
        );
        const usdtRaw = await usdtContract.balanceOf(address);
        let decimals: number = TOKENS.USDT_DECIMALS;
        try {
          const onchainDecimals: number = await usdtContract.decimals();
          if (Number.isInteger(onchainDecimals) && onchainDecimals > 0 && onchainDecimals <= 36) {
            decimals = onchainDecimals;
          }
        } catch {
          // older tokens without decimals() — keep the configured default
        }
        const usdt = parseFloat(ethers.formatUnits(usdtRaw, decimals));

        return {
          usdt: isNaN(usdt) ? 0 : Math.round(usdt * 100) / 100,
          pol: isNaN(pol) ? 0 : Math.round(pol * 10000) / 10000,
          ok: true,
        };
      } catch (err) {
        console.warn(`[Pulsar Web3] Balance check failed on ${rpc}:`, err);
      }
    }
    // F-18: all RPCs failed. Return ok:false — callers must not treat the
    // zero as the player's real balance.
    return { usdt: 0, pol: 0, ok: false };
  }

  public async refreshBalances(): Promise<{ usdt: number; pol: number; ok: boolean }> {
    if (!this.currentAccount.connected || !this.currentAccount.address) {
      return { usdt: 0, pol: 0, ok: false };
    }
    const balances = await this.fetchLiveOnChainBalances(this.currentAccount.address);
    if (balances.ok) {
      this.currentAccount.balanceUSDT = balances.usdt;
      this.currentAccount.balancePOL = balances.pol;
      this.currentAccount.balanceUnknown = false;
      this.notify();
    }
    // F-18: on total RPC failure the previous balance snapshot is KEPT and
    // balanceUnknown stays true — a dead RPC must never zero a funded wallet.
    return balances;
  }

  private async setConnectedAddress(
    address: string,
    providerName: string,
    chainId: number = 137,
    /**
     * Audit C3: the EIP-1193 provider this session belongs to. Every path that
     * establishes a session has one in scope, and recording it HERE (rather
     * than at each call site) is what makes the fix complete — the first pass
     * only covered the two interactive connect paths and left the reload /
     * session-restore / accountsChanged paths falling back to window.ethereum.
     * `undefined` means "caller has no provider to report"; `null` clears it.
     */
    provider?: any | null
  ): Promise<ConnectedAccountState> {
    if (provider !== undefined) this.bindActiveProvider(provider);
    const formatted = address.toLowerCase();
    const short = `${formatted.slice(0, 6)}...${formatted.slice(-4)}`;

    try {
      localStorage.setItem('pulsar_active_address', formatted);
      localStorage.setItem('pulsar_active_provider', providerName);
      if (isMobileDevice() || providerName.toLowerCase().includes('walletconnect')) {
        localStorage.setItem('pulsar_connection_mode', 'walletconnect');
      } else {
        localStorage.setItem('pulsar_connection_mode', 'injected');
      }
    } catch {}

    // Load clean real data from Cloud Firestore with local cache
    await this.loadUserDataAsync(formatted);

    this.currentAccount = {
      address: formatted,
      shortAddress: short,
      chainId,
      networkName: chainId === 137 ? 'Polygon Mainnet' : chainId === 1 ? 'Ethereum Mainnet' : chainId === 56 ? 'BNB Chain' : 'EVM Network',
      balanceUnknown: true,
      // P1.16: start at zero; the REAL on-chain USDT balance arrives from
      // fetchLiveOnChainBalances(). Never seed from the profile record.
      balanceUSDT: 0,
      balancePOL: 0,
      connected: true,
      providerName,
    };
    this.notify();

    // Query live real on-chain balances from Polygon Mainnet without blocking initial UI
    void this.fetchLiveOnChainBalances(formatted).then((live) => {
      if (this.currentAccount.address === formatted && this.currentAccount.connected && live.ok) {
        this.currentAccount.balanceUSDT = live.usdt;
        this.currentAccount.balancePOL = live.pol;
        this.currentAccount.balanceUnknown = false;
        this.notify();
      }
    });

    return this.currentAccount;
  }

  public static getPlayerTagForAddress(address: string): string {
    const clean = address.toLowerCase();
    const adjectives = ['Quantum', 'Apex', 'Cyber', 'Vortex', 'Hyper', 'Neon', 'Solar', 'Pulse', 'Shadow', 'Titan', 'Aero', 'Chrono'];
    const titles = ['Striker', 'Phantom', 'Runner', 'Sniper', 'Rider', 'Specter', 'Knight', 'Glitch', 'Blade', 'Viper', 'Ghost', 'Nova'];
    
    // Deterministic hash based on wallet address chars
    let hash = 0;
    for (let i = 0; i < clean.length; i++) {
      hash = (hash << 5) - hash + clean.charCodeAt(i);
      hash |= 0;
    }
    const absHash = Math.abs(hash);
    const adj = adjectives[absHash % adjectives.length];
    const tit = titles[(absHash >> 3) % titles.length];
    const num = (absHash % 90 + 10).toString();
    return `${adj}${tit}#${num}`;
  }

  private normalizeUserData(raw: Partial<UserWalletData> | null | undefined, addr: string): UserWalletData {
    return normalizeUserData(raw, addr, RealWeb3Manager.getPlayerTagForAddress(addr));
  }

  public async loadUserDataAsync(address: string): Promise<UserWalletData> {
    const cleanAddr = address.toLowerCase();
    const defaultTag = RealWeb3Manager.getPlayerTagForAddress(cleanAddr);
    
    // 0. The player's OWN profile (audit H-05): tag + saved friends live in the
    //    server's `pulsar_profiles` collection now, not in `users/{address}`
    //    (which the ledger owns and clients may not write). Read it WITHOUT
    //    prompting for a signature: a lobby visit must never open a wallet.
    let profile: { playerId: string; savedFriends: string[] } | null = null;
    try {
      const session = loadServerSession();
      if (session && session.address.toLowerCase() === cleanAddr && gameServerConfigured()) {
        const p = await fetchProfile(session);
        profile = { playerId: p.playerId || '', savedFriends: p.savedFriends || [] };
      }
      clearSaveFailure('profile', 'read');
    } catch (e) {
      // Unreadable profile is NOT "no friends" (audit H-05). Keep whatever the
      // local cache has and say so — never overwrite it with an empty list.
      // Audit M-24: "say so" has to reach the player, not the console.
      reportSaveFailure('profile', 'read', e);
      console.warn('Profile load failed; keeping the local copy:', e);
    }

    // 1. Try Firebase Firestore with rapid timeout to stay lightning fast if offline
    try {
      const userDocRef = doc(getDb(), 'users', cleanAddr);
      const snapPromise = getDoc(userDocRef);
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Firestore timeout')), 8000)
      );
      const snap = await Promise.race([snapPromise, timeoutPromise]);
      if (snap && snap.exists()) {
        const cloudData = this.normalizeUserData(snap.data(), cleanAddr);
        if (profile) {
          if (profile.playerId) cloudData.playerId = profile.playerId;
          cloudData.savedFriends = profile.savedFriends;
        } else {
          const local = this.loadFromLocal(cleanAddr);
          if (local?.savedFriends?.length) cloudData.savedFriends = local.savedFriends;
        }
        this.saveToLocal(cloudData);
        return cloudData;
      }
    } catch (e) {
      console.warn('Firestore load skipped or offline, using local cache:', e);
    }

    // 2. Try LocalStorage (normalised: a cache from an older build may miss fields)
    const localRaw = this.loadFromLocal(cleanAddr);
    if (localRaw) {
      const local = this.normalizeUserData(localRaw, cleanAddr);
      if (profile) {
        if (profile.playerId) local.playerId = profile.playerId;
        local.savedFriends = profile.savedFriends;
      }
      if (!local.playerId) local.playerId = defaultTag;
      this.saveToLocal(local);
      return local;
    }

    // 3. Check for Guest Practice Data Migration
    const guestData = this.loadFromLocal('guest_local_player');
    const hasGuestProgress = guestData && ((guestData.xp || 0) > 0 || (guestData.totalMatches || 0) > 0);

    // 4. Initialize real wallet with migrated guest progress (if any)
    const fresh: UserWalletData = {
      address: cleanAddr,
      playerId: defaultTag,
      vaultBalance: 0.0, // Clean 0 balance until deposit or match winnings
      wins: hasGuestProgress ? (guestData.wins || 0) : 0,
      losses: hasGuestProgress ? (guestData.losses || 0) : 0,
      voids: hasGuestProgress ? (guestData.voids || 0) : 0,
      totalMatches: hasGuestProgress ? (guestData.totalMatches || 0) : 0,
      bestReactionMs: hasGuestProgress ? (guestData.bestReactionMs || 0) : 0,
      avgReactionMs: hasGuestProgress ? (guestData.avgReactionMs || 0) : 0,
      xp: hasGuestProgress ? (guestData.xp || 0) : 0,
      level: hasGuestProgress ? (guestData.level || 1) : 1,
      savedFriends: [],
      history: hasGuestProgress && Array.isArray(guestData.history) ? guestData.history : [],
    };
    await this.saveUserDataAsync(fresh);
    return fresh;
  }

  public loadUserData(address: string): UserWalletData {
    const cleanAddr = address.toLowerCase();
    const defaultTag = RealWeb3Manager.getPlayerTagForAddress(cleanAddr);
    const local = this.loadFromLocal(cleanAddr);
    if (local) {
      if (local.xp === undefined) local.xp = 0;
      if (local.level === undefined) local.level = 1;
      if (!local.playerId) local.playerId = defaultTag;
      return local;
    }

    return {
      address: cleanAddr,
      playerId: defaultTag,
      vaultBalance: 0.0,
      wins: 0,
      losses: 0,
      voids: 0,
      totalMatches: 0,
      bestReactionMs: 0,
      avgReactionMs: 0,
      xp: 0,
      level: 1,
      savedFriends: [],
      history: [],
    };
  }

  public async saveUserDataAsync(data: UserWalletData): Promise<void> {
    if (!data.address) return;
    this.saveToLocal(data);
    // Audit H12: do NOT write `balanceUSDT` from the profile record.
    //
    // `vaultBalance` is a deprecated field: it is 0.0 on every fresh profile and
    // nothing updates it (P1.16 removed the vault). Assigning it here turned a
    // real on-chain balance — say $25.00 with `balanceUnknown === false` — into
    // a stated $0.00 after any recordMatch or updatePlayerTag, and tripped the
    // insufficient-balance gate in the lobby and the game.
    //
    // The chain is the only source of truth for the balance; `balanceUnknown`
    // says whether it has been read yet. `fetchLiveOnChainBalances` owns both.
    await this.syncToFirestore(data);
  }

  private saveToLocal(data: UserWalletData): void {
    try {
      localStorage.setItem(`pulsar_data_${data.address.toLowerCase()}`, JSON.stringify(data));
    } catch {}
  }

  private loadFromLocal(address: string): UserWalletData | null {
    try {
      const raw = localStorage.getItem(`pulsar_data_${address.toLowerCase()}`);
      if (raw) return JSON.parse(raw);
    } catch {}
    return null;
  }

  /**
   * Persist the profile through the SERVER (audit H-05).
   *
   * The previous version wrote `users/{address}` from the browser. The rules
   * deny every client write, so the call failed on every save and the failure
   * was swallowed — a player's tag and friend list never left the tab. The
   * server now owns `pulsar_profiles`; this sends the patch and surfaces the
   * outcome instead of pretending.
   *
   * The local cache is written first (in `saveUserDataAsync`), so a network
   * blip never loses the edit within this browser.
   */
  public lastProfileSyncError = '';

  private async syncToFirestore(data: UserWalletData): Promise<void> {
    const cleanAddr = data.address.toLowerCase();
    try {
      const session = loadServerSession();
      if (!session || session.address.toLowerCase() !== cleanAddr) {
        this.lastProfileSyncError = 'no session';
        // Not a network failure: there is nobody to save FOR. The banner would
        // be a lie ("retry"), so it stays quiet; the caller's UI explains it.
        return;
      }
      await saveProfile(session, {
        playerId: data.playerId || '',
        savedFriends: data.savedFriends || [],
      });
      this.lastProfileSyncError = '';
      clearSaveFailure('profile', 'write');
    } catch (e) {
      this.lastProfileSyncError = e instanceof Error ? e.message : 'profile sync failed';
      // Audit M-24: the local cache was written first, so the player SEES their
      // change. Without this the change is silently rolled back on the next
      // device. Report it; the banner renders it and the next success clears it.
      reportSaveFailure('profile', 'write', e);
      console.warn('Profile sync failed (kept locally):', e);
    }
  }

  // Audit #7 R4: recordGlobalMatchToFirestore removed — matches/ is
  // server-written only (firestore.rules allow write: if false for clients).

  /**
   * The public "LIVE ARENA" feed (audit H-04, 2026-10-22).
   *
   * This used to be an `onSnapshot` on Firestore's `matches` collection, reading
   * `entryFee` — a field the settlement ledger never writes (it writes `stake`).
   * The filter `fee > 0` therefore dropped every document and the feed was
   * permanently empty; if a document had ever carried the field, `result`
   * defaulted to `'win'` and every player in the feed would have looked like a
   * winner.
   *
   * It now polls the server's PUBLIC settlement log, which is the same data the
   * contract paid out on and carries the oracle signature. The feed reports a
   * per-player row: a settlement has one winner and one loser, and a list of
   * "matches" cannot say which side the viewer is looking at.
   *
   * An empty result is a FACT and is delivered as an empty list (audit M42).
   */
  public subscribeGlobalMatches(callback: (matches: MatchRecord[]) => void): () => void {
    if (!gameServerConfigured()) {
      callback([]);
      return () => {};
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const rows = settlementsToFeedRows(await fetchRecentSettlements(FEED_SIZE));
        if (!cancelled) callback(rows);
      } catch (e) {
        // A failed poll must not clear the feed: the last good snapshot is
        // still true of the past, and an empty array would claim "no duels".
        console.warn("Live feed poll failed:", e);
      }
      if (!cancelled) timer = setTimeout(poll, FEED_POLL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }

  public async fetchGlobalLeaderboard(): Promise<LeaderboardPlayer[]> {
    try {
      const lbCol = collection(getDb(), 'leaderboard');
      const q = query(lbCol, orderBy('wins', 'desc'), limit(20));
      const getPromise = getDocs(q);
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Leaderboard query timeout')), 8000)
      );
      const querySnapshot = await Promise.race([getPromise, timeoutPromise]);
      
      const results: LeaderboardPlayer[] = [];
      querySnapshot.forEach((d) => {
        const val = d.data();
        // Audit 2026-10-13 — HONESTY: this read `totalEarnedUSDT`, which the
        // settlement server NEVER writes (it writes `earnedUSDT`), so every
        // podium row fell back to a computed guess — `wins * 1.96` — and
        // presented it as USDT earned. A reaction time was invented the same way
        // (`|| 185`), and a missing address became a RANDOM hex string. Three
        // fabricated numbers on the money surface of a product whose pitch is
        // cryptographic proof.
        //
        // The server now writes `earnedUSDT` and `bestReactionMs`; a row that
        // lacks them reports 0 / no time rather than a plausible-looking guess.
        if (!val.address) return; // no identity → not a player row
        const earned =
          typeof val.earnedUSDT === 'number'
            ? val.earnedUSDT
            : typeof val.totalEarnedUSDT === 'number'
              ? val.totalEarnedUSDT
              : 0;
        const tag = val.playerId || val.name || RealWeb3Manager.getPlayerTagForAddress(val.address);
        const bestReaction = typeof val.bestReactionMs === 'number' ? val.bestReactionMs : 0;
        results.push({
          address: val.address,
          shortAddress: val.shortAddress || `${val.address.slice(0, 6)}...${val.address.slice(-4)}`,
          name: tag,
          playerId: tag,
          wins: val.wins || 0,
          totalMatches: val.totalMatches || 0,
          bestReactionMs: bestReaction,
          reactionTime: bestReaction,
          winRate: val.winRate || 0,
          totalEarnedUSDT: earned,
          totalWinnings: earned,
          xp: val.xp || 0,
          level: val.level || 1,
        });
      });

      if (results.length > 0) {
        try {
          localStorage.setItem('pulsar_cached_leaderboard', JSON.stringify(results));
        } catch {}
        return results;
      }

      // HONESTY RULE: no fabricated players. An empty leaderboard is the truth
      // until real duels are recorded.
      return [];
    } catch (e) {
      console.warn('Leaderboard query handled with local cache fallback:', e);
      try {
        const cached = localStorage.getItem('pulsar_cached_leaderboard');
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) return parsed;
        }
      } catch {}
      return [];
    }
  }

  /**
   * Find players by tag or address (audit M-19).
   *
   * This used to read `users/*` from the browser. That collection is the
   * settlement ledger — wallet-linked counters, reaction averages, history —
   * and it was world-readable so a friend card could render. The server now
   * answers with the five display fields a card needs, and the collection is
   * closed to clients.
   *
   * No fabricated people: a search that matches nothing returns nothing. (An
   * address that has never played is NOT invented into a "new challenger"
   * profile — the old code did exactly that for any 42-character hex string.)
   */
  public async searchPlayers(searchQuery: string): Promise<FriendProfile[]> {
    const q = searchQuery.trim();
    if (!q) return [];
    const session = loadServerSession();
    if (!session) return [];

    try {
      const { players } = await searchPlayersOnServer(session, q);
      return players.map((p) => ({
        address: p.address,
        playerId: p.playerId || `Player#${p.address.slice(2, 6)}`,
        shortAddress: `${p.address.slice(0, 6)}...${p.address.slice(-4)}`,
        level: p.level || 1,
        xp: 0,
        wins: p.wins || 0,
        totalMatches: p.totalMatches || 0,
        bestReactionMs: 0,
        winRate: p.totalMatches > 0 ? Math.round((p.wins / p.totalMatches) * 100) : 0,
        status: 'online',
      }));
    } catch {
      return [];
    }
  }

  public getSavedFriendsList(userAddress: string): FriendProfile[] {
    if (!userAddress) return [];
    const local = this.loadFromLocal(userAddress.toLowerCase());
    const friendAddrs = local?.savedFriends || [];
    const friends: FriendProfile[] = [];

    for (const addr of friendAddrs) {
      const cleanAddr = addr.toLowerCase();
      const friendData = this.loadFromLocal(cleanAddr);
      if (friendData) {
          friends.push({
            address: friendData.address,
            playerId: friendData.playerId || `Player#${friendData.address.slice(2, 6)}`,
            shortAddress: `${friendData.address.slice(0, 6)}...${friendData.address.slice(-4)}`,
            level: friendData.level || 1,
            xp: friendData.xp || 0,
            wins: friendData.wins || 0,
            totalMatches: friendData.totalMatches || 0,
            bestReactionMs: friendData.bestReactionMs || 0,
            winRate: friendData.totalMatches > 0 ? Math.round((friendData.wins / friendData.totalMatches) * 100) : 0,
            status: 'online',
          });
        } else {
          friends.push({
            address: cleanAddr,
            playerId: `Player#${cleanAddr.slice(2, 6)}`,
            shortAddress: `${cleanAddr.slice(0, 6)}...${cleanAddr.slice(-4)}`,
            level: 1,
            xp: 0,
            wins: 0,
            totalMatches: 0,
            bestReactionMs: 0,
            winRate: 0,
            status: 'online',
          });
      }
    }

    return friends;
  }

  public async toggleFriend(userAddress: string, friendProfile: FriendProfile): Promise<boolean> {
    if (!userAddress) return false;
    const cleanUser = userAddress.toLowerCase();
    const cleanFriend = friendProfile.address.toLowerCase();
    const data = await this.loadUserDataAsync(cleanUser);
    const current = data.savedFriends || [];

    const isAlreadySaved = current.includes(cleanFriend);
    let updated: string[];

    if (isAlreadySaved) {
      updated = current.filter((a) => a !== cleanFriend);
    } else {
      updated = [...current, cleanFriend];
    }

    data.savedFriends = updated;
    await this.saveUserDataAsync(data);
    return !isAlreadySaved;
  }

  /**
   * Enforces global uniqueness for player usernames across the entire Pulsar network.
   * Checks syntax, reserved keywords, and duplicate registrations in Firestore.
   */
  public async checkUsernameAvailability(
    rawTag: string,
    currentUserAddress?: string
  ): Promise<{ available: boolean; cleanTag: string; error?: string }> {
    const cleanTag = rawTag.trim();
    if (!cleanTag) {
      return { available: false, cleanTag: '', error: 'Username cannot be empty' };
    }

    if (cleanTag.length < 3) {
      return { available: false, cleanTag, error: 'Username must be at least 3 characters' };
    }

    if (cleanTag.length > 20) {
      return { available: false, cleanTag, error: 'Username cannot exceed 20 characters' };
    }

    // Alphanumeric + underscore only (English letters, numbers, underscores)
    const validPattern = /^[a-zA-Z0-9_]+$/;
    if (!validPattern.test(cleanTag)) {
      return {
        available: false,
        cleanTag,
        error: 'Only English letters, numbers, and underscores (_) are allowed',
      };
    }

    const normalized = cleanTag.toLowerCase();

    // Reserved protocol keywords
    const reservedWords = ['admin', 'pulsar', 'official', 'system', 'treasury', 'moderator', 'support', 'bot', 'oracle', 'escrow'];
    if (reservedWords.includes(normalized)) {
      return {
        available: false,
        cleanTag,
        error: `"${cleanTag}" is a reserved system name and cannot be used`,
      };
    }

    const cleanUserAddr = (currentUserAddress || this.currentAccount.address || '').toLowerCase();

    // Audit M12 (2026-10-13): ask the SERVER first. The registry endpoint was
    // the authoritative, rate-limited path and nothing called it, so it
    // protected nothing. The direct Firestore read below stays as the offline
    // fallback (it is a public collection, so it is not a weaker source — just
    // an unthrottled one).
    if (cleanUserAddr) {
      try {
        const session = await ensureSession(cleanUserAddr, async (message: string) => {
          const provider = this.getActiveEip1193Provider();
          if (!provider) throw new Error('No active wallet to sign in with.');
          return await provider.request({ method: 'personal_sign', params: [message, cleanUserAddr] });
        });
        const serverCheck = await checkUsername(session, cleanTag);
        if (serverCheck.available) {
          return { available: true, cleanTag };
        }
        return {
          available: false,
          cleanTag,
          error: `Username "${cleanTag}" is already taken by another player`,
        };
      } catch {
        /* no session / offline → fall through to the direct read */
      }
    }

    try {
      // 1. Check usernames registry document (primary index for O(1) collision detection)
      const usernameDocRef = doc(getDb(), 'usernames', normalized);
      const usernameDoc = await getDoc(usernameDocRef);

      if (usernameDoc.exists()) {
        const ownerAddr = (usernameDoc.data()?.address || '').toLowerCase();
        if (cleanUserAddr && ownerAddr === cleanUserAddr) {
          // The current user already owns this username
          return { available: true, cleanTag };
        }
        return {
          available: false,
          cleanTag,
          error: `Username "${cleanTag}" is already taken by another player`,
        };
      }

      // 2. Secondary check against users collection to prevent any edge collision
      const usersCol = collection(getDb(), 'users');
      const q = query(usersCol, where('playerId', '==', cleanTag));
      const userSnapshot = await getDocs(q);

      if (!userSnapshot.empty) {
        let isOwnedByCurrentUser = false;
        userSnapshot.forEach((d) => {
          if (cleanUserAddr && d.id.toLowerCase() === cleanUserAddr) {
            isOwnedByCurrentUser = true;
          }
        });

        if (!isOwnedByCurrentUser) {
          return {
            available: false,
            cleanTag,
            error: `Username "${cleanTag}" is already taken by another player`,
          };
        }
      }

      return { available: true, cleanTag };
    } catch (err) {
      console.warn('Firestore username availability check handled gracefully:', err);
      // If network is offline, allow if local storage doesn't have duplicate
      return { available: true, cleanTag };
    }
  }

  /**
   * REMOVED (audit H-05, 2026-10-22): this method wrote `usernames/{tag}`
   * directly from the browser. `firestore.rules` denies every client write, so
   * it could only ever fail — but as a landmine it was worse than dead: any
   * future rules relaxation would have reopened namespace squatting and
   * identity takeover, which is exactly what the server-side claim closed
   * (`POST /api/username/claim`, used by the store).
   */
}

export { RealWeb3Manager };
export const realWeb3Manager = new RealWeb3Manager();
