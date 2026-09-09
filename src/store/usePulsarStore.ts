import { useSyncExternalStore } from 'react';
import { WalletState, UserStats, MatchHistoryItem } from '../types';
import { realWeb3Manager, RealWeb3Manager, UserWalletData, LeaderboardPlayer, ConnectedAccountState } from '../lib/realWeb3';
import { EIP6963ProviderDetail } from '../lib/eip6963';
import { XPSystem, XPSummary } from '../lib/xpSystem';
import { loadPersistedSiweSession } from '../lib/siwe';

/**
 * P0.7 — Single shared store.
 *
 * The previous implementation was a hook that created independent copies of
 * account/user/leaderboard state (and separate manager subscriptions) in
 * every component, so "balance" and "wins" could diverge between screens.
 * Now all state lives in ONE module-level snapshot, and every component
 * subscribes to the same instance via useSyncExternalStore. The public API
 * of this hook is unchanged, so no consumer had to be rewritten.
 */

const EMPTY_USER_DATA: UserWalletData = {
  address: '',
  vaultBalance: 0,
  wins: 0,
  losses: 0,
  voids: 0,
  totalMatches: 0,
  bestReactionMs: 0,
  avgReactionMs: 0,
  xp: 0,
  level: 1,
  history: [],
};

interface PulsarSnapshot {
  account: ConnectedAccountState;
  userData: UserWalletData;
  leaderboard: LeaderboardPlayer[];
  signatureVerified: boolean;
  lastMatchXPSummary: XPSummary | null;
}

let account: ConnectedAccountState = { ...realWeb3Manager.getAccount() };
let userData: UserWalletData = EMPTY_USER_DATA;
let leaderboard: LeaderboardPlayer[] = [];
let signatureVerified = !!loadPersistedSiweSession();
let lastMatchXPSummary: XPSummary | null = null;
let snapshot: PulsarSnapshot = buildSnapshot();
let lastLoadedAddress = '';
let bootstrapped = false;

function buildSnapshot(): PulsarSnapshot {
  return { account, userData, leaderboard, signatureVerified, lastMatchXPSummary };
}

function commit() {
  snapshot = buildSnapshot();
}

function reloadUserDataIfStale() {
  if (account.connected && account.address && account.address !== lastLoadedAddress) {
    lastLoadedAddress = account.address;
    realWeb3Manager
      .loadUserDataAsync(account.address)
      .then((data) => {
        userData = data;
        commit();
      })
      .catch(() => {});
  } else if (!account.connected && lastLoadedAddress) {
    lastLoadedAddress = '';
    userData = EMPTY_USER_DATA;
    commit();
  }
}

// One subscription for the entire app (instead of one per component).
realWeb3Manager.subscribe(() => {
  account = { ...realWeb3Manager.getAccount() };
  commit();
  reloadUserDataIfStale();
});

function bootstrap() {
  if (bootstrapped || typeof window === 'undefined') return;
  bootstrapped = true;
  realWeb3Manager.restoreSession().catch(() => {});
  realWeb3Manager.fetchGlobalLeaderboard().then((lb) => {
    if (lb.length > 0) {
      leaderboard = lb;
      commit();
    }
  });
}

const setLeaderboard = (lb: LeaderboardPlayer[]) => {
  leaderboard = lb;
  commit();
};

const setUserData = (data: UserWalletData) => {
  userData = data;
  commit();
};

const setAccountFrom = (acc: ConnectedAccountState) => {
  account = { ...acc };
  commit();
  reloadUserDataIfStale();
};

const connectWallet = async (
  provider: string = 'MetaMask',
  onUri?: (uri: string, deepLink: string, nativeScheme?: string) => void
) => {
  const acc = await realWeb3Manager.connect(provider, onUri);
  if (acc) {
    setAccountFrom(acc);
    const data = await realWeb3Manager.loadUserDataAsync(acc.address);
    setUserData(data);
    realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
    return acc;
  }
  return undefined;
};

const cancelPendingConnect = () => {
  realWeb3Manager.cancelPendingConnect();
};

const connectEIP6963 = async (providerDetail: EIP6963ProviderDetail) => {
  const acc = await realWeb3Manager.connectEIP6963(providerDetail);
  if (acc) {
    setAccountFrom(acc);
    const data = await realWeb3Manager.loadUserDataAsync(acc.address);
    setUserData(data);
    realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
    return acc;
  }
  return undefined;
};

const connectWalletConnect = async (onUri?: (uri: string) => void) => {
  const acc = await realWeb3Manager.connectWalletConnect(onUri);
  if (acc) {
    setAccountFrom(acc);
    const data = await realWeb3Manager.loadUserDataAsync(acc.address);
    setUserData(data);
    realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
    return acc;
  }
  return undefined;
};

const connectDirectWallet = async (address: string, providerName?: string) => {
  const acc = await realWeb3Manager.connectDirect(address, providerName || 'EVM Wallet');
  if (acc) {
    setAccountFrom(acc);
    const data = await realWeb3Manager.loadUserDataAsync(acc.address);
    setUserData(data);
    realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
    return acc;
  }
  return undefined;
};

// P0.5 — SIWE (EIP-4361): prove wallet ownership before any privileged action.
const requestSignature = async (): Promise<boolean> => {
  const addr = account.connected ? account.address : '';
  if (!addr) return false;
  const message = realWeb3Manager.buildOwnershipMessage(addr);
  const provider = realWeb3Manager.getActiveEip1193Provider();
  if (!provider) throw new Error('No active wallet is connected to sign the message.');
  try {
    const signature: string = await provider.request({ method: 'signMessage', params: [addr, message] });
    const verified = await realWeb3Manager.verifyOwnershipSignature(addr, message, signature);
    if (verified) {
      signatureVerified = true;
      commit();
    }
    return verified;
  } catch (err: any) {
    const msg = String(err?.message || err || '');
    if (msg.includes('signMessage') || err?.code === -32601 || err?.code === -32602) {
      try {
        const signature: string = await provider.request({ method: 'personal_sign', params: [message, addr] });
        const verified = await realWeb3Manager.verifyOwnershipSignature(addr, message, signature);
        if (verified) {
          signatureVerified = true;
          commit();
        }
        return verified;
      } catch (err2: any) {
        if (err2?.code === 4001) throw new Error('Signature request was cancelled in your wallet.');
        throw err2;
      }
    }
    if (err?.code === 4001) throw new Error('Signature request was cancelled in your wallet.');
    throw err;
  }
};

const disconnectWallet = () => {
  try { localStorage.removeItem('pulsar_siwe_session'); } catch {}
  signatureVerified = false;
  realWeb3Manager.disconnect();
  account = { ...realWeb3Manager.getAccount() };
  userData = EMPTY_USER_DATA;
  lastLoadedAddress = '';
  commit();
};

const refreshBalance = async () => {
  return await realWeb3Manager.refreshBalances();
};

const recordMatch = async (match: MatchHistoryItem): Promise<XPSummary> => {
  const userAddress = account.connected && account.address ? account.address : 'guest_local_player';

  const data = await realWeb3Manager.loadUserDataAsync(userAddress);
  const currentXP = data.xp || 0;

  // Calculate XP with accurate dynamic rewards (Practice games grant balanced training XP)
  const xpCalc = XPSystem.calculateMatchXP(
    match.result,
    match.entryFee,
    match.yourTime,
    currentXP
  );

  match.xpEarned = xpCalc.totalAwardedXP;
  lastMatchXPSummary = xpCalc;

  const updatedHistory = [match, ...data.history].slice(0, 50);
  data.totalMatches += 1;
  data.xp = xpCalc.newTotalXP;
  data.level = xpCalc.newLevel;

  if (match.result === 'win') {
    data.wins += 1;
    // P1.16: money settles ON-CHAIN via PulsarEscrow.settleDuel(). The local
    // record tracks performance only — it must never mutate a balance.
  } else if (match.result === 'loss') {
    data.losses += 1;
  } else {
    data.voids += 1;
  }

  if (match.yourTime > 0) {
    if (data.bestReactionMs === 0 || match.yourTime < data.bestReactionMs) {
      data.bestReactionMs = match.yourTime;
    }
    data.avgReactionMs =
      data.avgReactionMs === 0
        ? match.yourTime
        : Math.round((data.avgReactionMs * (data.totalMatches - 1) + match.yourTime) / data.totalMatches);
  }

  data.history = updatedHistory;
  await realWeb3Manager.saveUserDataAsync(data);
  setUserData({ ...data });

  // Refresh cloud leaderboard
  realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
  return xpCalc;
};

const depositFunds = async (_amount?: number) => {
  // P1.16: "deposit" = refresh the REAL on-chain USDT balance. There is no
  // in-app vault; funds move only through the escrow contract.
  await realWeb3Manager.refreshBalances();
};

const withdrawFunds = async (_amount: number) => {
  // P1.16: removed. The previous implementation silently decremented a
  // database number — a phantom withdrawal. Real withdrawals are
  // escrow.withdrawVault()/settleDuel() transactions (see lib/escrowFlow.ts).
  throw new Error(
    'Withdrawals happen on-chain via the escrow contract. Connect a wallet and use the escrow withdraw flow.'
  );
};

const updatePlayerTag = async (newTag: string): Promise<{ success: boolean; error?: string }> => {
  if (!account.connected || !account.address) {
    return { success: false, error: 'Please connect your wallet first' };
  }
  const result = await realWeb3Manager.claimUsername(newTag, account.address);
  if (result.success) {
    const updated = await realWeb3Manager.loadUserDataAsync(account.address);
    setUserData(updated);
  }
  return result;
};

const checkUsernameAvailability = async (tag: string) => {
  return await realWeb3Manager.checkUsernameAvailability(tag, account.address || undefined);
};

const updateBenchmarkSpeed = async (speedMs: number) => {
  if (speedMs <= 0) return;
  const userAddress = account.connected && account.address ? account.address : 'guest_local_player';
  const data = await realWeb3Manager.loadUserDataAsync(userAddress);
  if (data.bestReactionMs === 0 || speedMs < data.bestReactionMs) {
    data.bestReactionMs = speedMs;
  }
  if (data.avgReactionMs === 0) {
    data.avgReactionMs = speedMs;
  } else {
    data.avgReactionMs = Math.round((data.avgReactionMs + speedMs) / 2);
  }
  await realWeb3Manager.saveUserDataAsync(data);
  setUserData({ ...data });
};

export function usePulsarStore() {
  bootstrap();

  const state = useSyncExternalStore(
    (onChange) => realWeb3Manager.subscribe(onChange),
    () => snapshot,
    () => snapshot
  );

  const currentUsdtBalance =
    state.account.balanceUSDT !== undefined && !isNaN(state.account.balanceUSDT)
      ? state.account.balanceUSDT
      : state.userData.vaultBalance || 0;

  const walletState: WalletState = {
    connected: state.account.connected,
    provider: state.account.providerName || null,
    address: state.account.shortAddress || state.account.address,
    fullAddress: state.account.address,
    playerId:
      state.userData.playerId ||
      (state.account.address ? RealWeb3Manager.getPlayerTagForAddress(state.account.address) : undefined),
    balance: currentUsdtBalance,
    balancePOL: state.account.balancePOL || 0,
  };

  const statsState: UserStats = {
    balance: currentUsdtBalance,
    wins: state.userData.wins,
    losses: state.userData.losses,
    voids: state.userData.voids,
    totalMatches: state.userData.totalMatches,
    xp: state.userData.xp || 0,
    level: state.userData.level || 1,
    playerId:
      state.userData.playerId ||
      (state.account.address ? RealWeb3Manager.getPlayerTagForAddress(state.account.address) : undefined),
    bestReactionMs: state.userData.bestReactionMs,
    avgReactionMs: state.userData.avgReactionMs,
  };

  return {
    wallet: walletState,
    rawAccount: state.account,
    stats: statsState,
    history: state.userData.history,
    leaderboard: state.leaderboard,
    bestReactionMs: state.userData.bestReactionMs,
    avgReactionMs: state.userData.avgReactionMs,
    lastMatchXPSummary: state.lastMatchXPSummary,
    signatureVerified: state.signatureVerified,
    requestSignature,
    connectWallet,
    connectEIP6963,
    connectWalletConnect,
    connectDirectWallet,
    cancelPendingConnect,
    disconnectWallet,
    refreshBalance,
    recordMatch,
    depositFunds,
    withdrawFunds,
    updatePlayerTag,
    checkUsernameAvailability,
    updateBenchmarkSpeed,
  };
}
