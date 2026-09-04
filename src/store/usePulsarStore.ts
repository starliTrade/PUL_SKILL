import { useState, useEffect } from 'react';
import { WalletState, UserStats, MatchHistoryItem } from '../types';
import { realWeb3Manager, RealWeb3Manager, UserWalletData, LeaderboardPlayer, SEED_LEADERBOARD } from '../lib/realWeb3';
import { EIP6963ProviderDetail } from '../lib/eip6963';
import { XPSystem, XPSummary } from '../lib/xpSystem';

export function usePulsarStore() {
  const [account, setAccount] = useState(realWeb3Manager.getAccount());
  const [leaderboard, setLeaderboard] = useState<LeaderboardPlayer[]>(() => {
    try {
      const cached = localStorage.getItem('pulsar_cached_leaderboard');
      if (cached) {
        const parsed = JSON.parse(cached);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {}
    return SEED_LEADERBOARD;
  });
  const [lastMatchXPSummary, setLastMatchXPSummary] = useState<XPSummary | null>(null);
  const [userData, setUserData] = useState<UserWalletData>(() => {
    const acc = realWeb3Manager.getAccount();
    if (acc.connected && acc.address) {
      return realWeb3Manager.loadUserData(acc.address);
    }
    return {
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
  });

  useEffect(() => {
    // Initial fetch of cloud leaderboard
    realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);

    const unsubscribe = realWeb3Manager.subscribe(() => {
      const currentAcc = realWeb3Manager.getAccount();
      setAccount({ ...currentAcc });
      if (currentAcc.connected && currentAcc.address) {
        realWeb3Manager.loadUserDataAsync(currentAcc.address).then((data) => {
          setUserData(data);
        });
      } else {
        setUserData({
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
        });
      }
    });

    return () => unsubscribe();
  }, []);

  const connectWallet = async (
    provider: string = 'MetaMask',
    onUri?: (uri: string, deepLink: string, nativeScheme?: string) => void
  ) => {
    try {
      const acc = await realWeb3Manager.connect(provider, onUri);
      if (acc) {
        setAccount({ ...acc });
        const data = await realWeb3Manager.loadUserDataAsync(acc.address);
        setUserData(data);
        realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
        return acc;
      }
    } catch (err) {
      throw err;
    }
  };

  const cancelPendingConnect = () => {
    realWeb3Manager.cancelPendingConnect();
  };

  const connectEIP6963 = async (providerDetail: EIP6963ProviderDetail) => {
    try {
      const acc = await realWeb3Manager.connectEIP6963(providerDetail);
      if (acc) {
        setAccount({ ...acc });
        const data = await realWeb3Manager.loadUserDataAsync(acc.address);
        setUserData(data);
        realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
        return acc;
      }
    } catch (err) {
      throw err;
    }
  };

  const connectWalletConnect = async (onUri?: (uri: string) => void) => {
    try {
      const acc = await realWeb3Manager.connectWalletConnect(onUri);
      if (acc) {
        setAccount({ ...acc });
        const data = await realWeb3Manager.loadUserDataAsync(acc.address);
        setUserData(data);
        realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
        return acc;
      }
    } catch (err) {
      throw err;
    }
  };

  const connectDirectWallet = async (address: string, providerName?: string) => {
    const acc = await realWeb3Manager.connectDirect(address, providerName || 'EVM Wallet');
    if (acc) {
      setAccount({ ...acc });
      const data = await realWeb3Manager.loadUserDataAsync(acc.address);
      setUserData(data);
      realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
      return acc;
    }
  };

  const connectInstantGuestWallet = async () => {
    const acc = await realWeb3Manager.connectInstantGuestWallet();
    if (acc) {
      setAccount({ ...acc });
      const data = await realWeb3Manager.loadUserDataAsync(acc.address);
      setUserData(data);
      realWeb3Manager.fetchGlobalLeaderboard().then(setLeaderboard);
      return acc;
    }
  };

  const disconnectWallet = () => {
    realWeb3Manager.disconnect();
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
    setLastMatchXPSummary(xpCalc);

    const updatedHistory = [match, ...data.history].slice(0, 50);
    data.totalMatches += 1;
    data.xp = xpCalc.newTotalXP;
    data.level = xpCalc.newLevel;

    if (match.result === 'win') {
      data.wins += 1;
      if (match.entryFee > 0) {
        data.vaultBalance = parseFloat((data.vaultBalance + match.prize - match.entryFee).toFixed(2));
      }
    } else if (match.result === 'loss') {
      data.losses += 1;
      if (match.entryFee > 0) {
        data.vaultBalance = parseFloat(Math.max(0, data.vaultBalance - match.entryFee).toFixed(2));
      }
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

  const depositFunds = async (amount: number) => {
    if (!account.connected || !account.address) return;
    const data = await realWeb3Manager.loadUserDataAsync(account.address);
    data.vaultBalance = parseFloat((data.vaultBalance + amount).toFixed(2));
    await realWeb3Manager.saveUserDataAsync(data);
    setUserData({ ...data });
  };

  const withdrawFunds = async (amount: number) => {
    if (!account.connected || !account.address) return;
    const data = await realWeb3Manager.loadUserDataAsync(account.address);
    if (data.vaultBalance >= amount) {
      data.vaultBalance = parseFloat((data.vaultBalance - amount).toFixed(2));
      await realWeb3Manager.saveUserDataAsync(data);
      setUserData({ ...data });
    }
  };

  const walletState: WalletState = {
    connected: account.connected,
    provider: account.providerName || null,
    address: account.shortAddress || account.address,
    fullAddress: account.address,
    playerId: userData.playerId || (account.address ? RealWeb3Manager.getPlayerTagForAddress(account.address) : undefined),
    balance: userData.vaultBalance,
  };

  const statsState: UserStats = {
    balance: userData.vaultBalance,
    wins: userData.wins,
    losses: userData.losses,
    voids: userData.voids,
    totalMatches: userData.totalMatches,
    xp: userData.xp || 0,
    level: userData.level || 1,
    playerId: userData.playerId || (account.address ? RealWeb3Manager.getPlayerTagForAddress(account.address) : undefined),
  };

  return {
    wallet: walletState,
    rawAccount: account,
    stats: statsState,
    history: userData.history,
    leaderboard,
    bestReactionMs: userData.bestReactionMs,
    avgReactionMs: userData.avgReactionMs,
    lastMatchXPSummary,
    connectWallet,
    connectEIP6963,
    connectWalletConnect,
    connectDirectWallet,
    connectInstantGuestWallet,
    cancelPendingConnect,
    disconnectWallet,
    recordMatch,
    depositFunds,
    withdrawFunds,
  };
}
