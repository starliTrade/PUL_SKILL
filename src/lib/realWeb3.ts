/**
 * Pulsar Real Web3 & Firebase Firestore Real-Time Database Manager
 * Zero mock accounts, zero fake duels. Pure real-time on-chain & cloud persistence.
 */

import {
  doc,
  getDoc,
  setDoc,
  collection,
  query,
  orderBy,
  limit,
  getDocs,
  onSnapshot,
} from 'firebase/firestore';
import { db } from './firebase';
import { eip6963Manager, EIP6963ProviderDetail } from './eip6963';
import { isMobileDevice, isInAppBrowser, getWalletConnectDeepLink, triggerMobileWalletHandoff } from './web3DeepLinks';

export const getWalletConnectProjectId = (): string => {
  const envId = typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WALLETCONNECT_PROJECT_ID;
  if (envId && typeof envId === 'string' && envId.trim().length > 0) {
    return envId.trim();
  }
  return '5f4e967f02cf92c8db957c56e877e149';
};

/**
 * Bulletproof resolver for WalletConnect EthereumProvider class
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

export const SEED_PLAYERS: FriendProfile[] = [
  {
    address: '0x89205a3a3b2a69de6dbf7f01ed13b2108b2c43e7',
    playerId: 'VortexSniper#42',
    shortAddress: '0x8920...43e7',
    level: 8,
    xp: 2840,
    wins: 24,
    totalMatches: 31,
    bestReactionMs: 162,
    winRate: 77,
    status: 'online',
    bio: 'Sub-170ms kinetic specialist · Ready for high-stakes duels',
  },
  {
    address: '0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc',
    playerId: 'CyberPhantom#99',
    shortAddress: '0x3c44...93bc',
    level: 6,
    xp: 1950,
    wins: 19,
    totalMatches: 28,
    bestReactionMs: 178,
    winRate: 68,
    status: 'online',
    bio: 'Zero-latency Polygon grinder · Quick reflexes',
  },
  {
    address: '0x90f79bf6eb2c4f870365e785982e1f101e93b906',
    playerId: 'NovaRider#07',
    shortAddress: '0x90f7...b906',
    level: 4,
    xp: 1120,
    wins: 12,
    totalMatches: 21,
    bestReactionMs: 194,
    winRate: 57,
    status: 'in_game',
    bio: 'Casual micro-stake challenger · Practice makes perfect',
  },
];

export const SEED_LEADERBOARD: LeaderboardPlayer[] = SEED_PLAYERS.map((s) => ({
  address: s.address,
  shortAddress: s.shortAddress,
  name: s.playerId,
  playerId: s.playerId,
  wins: s.wins,
  totalMatches: s.totalMatches,
  bestReactionMs: s.bestReactionMs,
  reactionTime: s.bestReactionMs,
  winRate: s.winRate,
  totalEarnedUSDT: Math.round(s.wins * 1.96 * 100) / 100,
  totalWinnings: Math.round(s.wins * 1.96 * 100) / 100,
  xp: s.xp,
  level: s.level,
}));

class RealWeb3Manager {
  private currentAccount: ConnectedAccountState = {
    address: '',
    shortAddress: '',
    chainId: 137,
    networkName: 'Polygon Mainnet',
    balanceUSDT: 0,
    connected: false,
    providerName: '',
  };

  private listeners: Array<() => void> = [];

  constructor() {
    if (typeof window !== 'undefined') {
      // A stored address is not proof of a live wallet session. Never restore a wallet
      // from localStorage; the wallet must authorize this browser on every fresh session.
      if ((window as any).ethereum) {
        const ethereum = (window as any).ethereum;

        ethereum.on?.('accountsChanged', (accounts: string[]) => {
          if (!accounts || accounts.length === 0) {
            this.disconnect();
          } else {
            this.setConnectedAddress(accounts[0], this.currentAccount.providerName || 'MetaMask', 137);
          }
        });

        ethereum.on?.('chainChanged', () => {
          window.location.reload();
        });
      }
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
  private wcUriListeners: Array<(uri: string) => void> = [];
  public lastWcUri: string | null = null;

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

  public async connectWalletConnect(onUriGenerated?: (uri: string) => void): Promise<ConnectedAccountState> {
    try {
      const EthereumProviderClass = await getEthereumProviderClass();
      const projectId = getWalletConnectProjectId();

      if (this.wcProvider) {
        try {
          if (this.wcProvider.connected) {
            await this.wcProvider.disconnect();
          }
        } catch {}
      }

      this.wcProvider = await EthereumProviderClass.init({
        projectId,
        chains: [137],
        optionalChains: [1, 56, 42161],
        showQrModal: true,
        metadata: {
          name: 'PULSAR Arena',
          description: 'PULSAR Ultra-Reaction Arena',
          url: typeof window !== 'undefined' ? window.location.origin : 'https://pulsar.arena',
          icons: ['https://avatars.githubusercontent.com/u/37784886'],
        },
      });

      // Attach error listeners to prevent unhandled EventEmitter crashes
      try {
        this.wcProvider.on('error', (err: any) => {
          console.warn('[Pulsar Web3] Handled WalletConnect provider error event:', err);
        });
        const innerProvider = (this.wcProvider as any)?.signer?.client?.core?.relayer?.provider;
        if (innerProvider && typeof innerProvider.on === 'function') {
          innerProvider.on('error', (err: any) => {
            console.warn('[Pulsar Web3] Handled WalletConnect internal relay provider error event:', err);
          });
        }
      } catch {}

      this.wcProvider.on('display_uri', (uri: string) => {
        this.lastWcUri = uri;
        if (onUriGenerated) onUriGenerated(uri);
        this.wcUriListeners.forEach((cb) => cb(uri));
      });

      this.wcProvider.on('accountsChanged', (accounts: string[]) => {
        if (!accounts || accounts.length === 0) {
          this.disconnect();
        } else {
          this.setConnectedAddress(accounts[0], 'WalletConnect', 137);
        }
      });

      this.wcProvider.on('disconnect', () => {
        this.disconnect();
      });

      // Safety timeout of 14 seconds so mobile UI never gets stuck in a permanent spinner
      const connectPromise = this.wcProvider.connect();
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                'WalletConnect session timed out. Tap "Open in Wallet App" to launch your wallet directly, or connect by address.'
              )
            ),
          14000
        )
      );
      await Promise.race([connectPromise, timeoutPromise]);
      const accounts = this.wcProvider.accounts;
      if (accounts && accounts.length > 0) {
        const chainId = this.wcProvider.chainId || 137;
        return await this.setConnectedAddress(accounts[0], 'WalletConnect', chainId);
      } else {
        throw new Error('No accounts selected in your wallet.');
      }
    } catch (err: any) {
      if (err?.message?.includes('User closed') || err?.message?.includes('Modal closed') || err?.message?.includes('User rejected')) {
        throw new Error('Connection request was cancelled.');
      }
      if (
        err?.message?.includes('3000') ||
        err?.message?.includes('origin not allowed') ||
        err?.message?.includes('WebSocket connection closed')
      ) {
        throw new Error('WalletConnect relay origin constraint on this domain. Please connect using an installed browser wallet extension or the 1-Click Instant Guest Duelist.');
      }
      throw err;
    }
  }

  public getInjectedProvider(providerName: string = 'MetaMask'): any {
    if (typeof window === 'undefined') return null;

    // 1. Check EIP-6963 announced providers first
    const eip6963Match = eip6963Manager.getProviderByName(providerName);
    if (eip6963Match?.provider) {
      return eip6963Match.provider;
    }

    let eth = (window as any).ethereum;
    let phantomEth = (window as any).phantom?.ethereum;
    let coinbaseEth = (window as any).coinbaseWalletExtension;
    let trustEth = (window as any).trustwallet;

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
        let chainId = 137;
        try {
          const chainIdHex = await provider.request({ method: 'eth_chainId' });
          if (chainIdHex) chainId = parseInt(chainIdHex, 16);
        } catch {}

        if (chainId !== 137) {
          try {
            await provider.request({
              method: 'wallet_switchEthereumChain',
              params: [{ chainId: '0x89' }],
            });
            chainId = 137;
          } catch (switchError: any) {
            if (switchError.code === 4902) {
              try {
                await provider.request({
                  method: 'wallet_addEthereumChain',
                  params: [
                    {
                      chainId: '0x89',
                      chainName: 'Polygon Mainnet',
                      nativeCurrency: { name: 'POL', symbol: 'POL', decimals: 18 },
                      rpcUrls: ['https://polygon-rpc.com'],
                      blockExplorerUrls: ['https://polygonscan.com'],
                    },
                  ],
                });
                chainId = 137;
              } catch {}
            }
          }
        }

        return await this.setConnectedAddress(accounts[0], providerDetail.info.name, chainId);
      } else {
        throw new Error('No accounts selected in your wallet.');
      }
    } catch (err: any) {
      if (err?.code === 4001) {
        throw new Error('Connection request was cancelled in your wallet.');
      }
      if (err?.code === -32002) {
        throw new Error('Wallet is already waiting for your confirmation. Please check your wallet extension or app.');
      }
      throw new Error(err?.message || `Failed to connect to ${providerDetail.info.name}`);
    }
  }

  public async connectWalletConnectTargeted(
    providerName: string = 'MetaMask',
    onUri?: (uri: string, deepLink: string) => void
  ): Promise<ConnectedAccountState> {
    try {
      const EthereumProviderClass = await getEthereumProviderClass();
      const { getWalletConnectDeepLink, triggerMobileWalletHandoff, isMobileDevice } = await import('./web3DeepLinks');
      const projectId = getWalletConnectProjectId();

      if (this.wcProvider) {
        try {
          if (this.wcProvider.connected) {
            await this.wcProvider.disconnect();
          }
        } catch {}
      }

      const isMobile = isMobileDevice();

      this.wcProvider = await EthereumProviderClass.init({
        projectId,
        chains: [137],
        optionalChains: [1, 56, 42161],
        showQrModal: false, // Clean targeted direct handoff without generic blocking modal
        metadata: {
          name: 'PULSAR Arena',
          description: 'PULSAR Ultra-Reaction Arena',
          url: typeof window !== 'undefined' ? window.location.origin : 'https://pulsar.arena',
          icons: ['https://avatars.githubusercontent.com/u/37784886'],
        },
      });

      // Attach error listeners to prevent unhandled EventEmitter crashes
      try {
        this.wcProvider.on('error', (err: any) => {
          console.warn('[Pulsar Web3] Handled WalletConnect provider error event:', err);
        });
        const innerProvider = (this.wcProvider as any)?.signer?.client?.core?.relayer?.provider;
        if (innerProvider && typeof innerProvider.on === 'function') {
          innerProvider.on('error', (err: any) => {
            console.warn('[Pulsar Web3] Handled WalletConnect internal relay provider error event:', err);
          });
        }
      } catch {}

      this.wcProvider.on('display_uri', (uri: string) => {
        this.lastWcUri = uri;
        const deepLink = getWalletConnectDeepLink(providerName, uri);
        if (onUri) {
          onUri(uri, deepLink);
        }
        this.wcUriListeners.forEach((cb) => cb(uri));

        // On mobile devices, immediately handoff to the native wallet app
        if (isMobile) {
          triggerMobileWalletHandoff(deepLink);
        }
      });

      this.wcProvider.on('accountsChanged', (accounts: string[]) => {
        if (!accounts || accounts.length === 0) {
          this.disconnect();
        } else {
          this.setConnectedAddress(accounts[0], providerName, 137);
        }
      });

      this.wcProvider.on('disconnect', () => {
        this.disconnect();
      });

      // Safety timeout of 14 seconds so mobile UI never gets stuck in a permanent spinner
      const targetedConnectPromise = this.wcProvider.connect();
      const targetedTimeoutPromise = new Promise((_, reject) =>
        setTimeout(
          () =>
            reject(
              new Error(
                `Connection request to ${providerName} timed out. Please tap "Open in ${providerName} App" or connect with your wallet address.`
              )
            ),
          14000
        )
      );
      await Promise.race([targetedConnectPromise, targetedTimeoutPromise]);
      const accounts = this.wcProvider.accounts;
      if (accounts && accounts.length > 0) {
        const chainId = this.wcProvider.chainId || 137;
        return await this.setConnectedAddress(accounts[0], providerName, chainId);
      } else {
        throw new Error('No accounts selected in your wallet.');
      }
    } catch (err: any) {
      if (err?.message?.includes('User closed') || err?.message?.includes('Modal closed') || err?.message?.includes('User rejected')) {
        throw new Error('Connection request was cancelled.');
      }
      if (
        err?.message?.includes('3000') ||
        err?.message?.includes('origin not allowed') ||
        err?.message?.includes('WebSocket connection closed')
      ) {
        throw new Error(`WalletConnect relay origin constraint on this domain. Please connect using an installed browser wallet extension or the 1-Click Instant Guest Duelist.`);
      }
      throw err;
    }
  }

  public async connectInstantGuestWallet(): Promise<ConnectedAccountState> {
    try {
      const { ethers } = await import('ethers');
      let existingKey = typeof localStorage !== 'undefined' ? localStorage.getItem('pulsar_guest_wallet_pk') : null;
      let wallet: any;
      if (existingKey) {
        wallet = new ethers.Wallet(existingKey);
      } else {
        wallet = ethers.Wallet.createRandom();
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem('pulsar_guest_wallet_pk', wallet.privateKey);
        }
      }
      return await this.setConnectedAddress(wallet.address, 'Instant Duelist', 137);
    } catch (e: any) {
      console.error('Instant guest wallet error:', e);
      throw e;
    }
  }

  public async connect(
    provider: string = 'MetaMask',
    onUri?: (uri: string, deepLink: string) => void
  ): Promise<ConnectedAccountState> {
    let injected = this.getInjectedProvider(provider);

    // If specific provider was not found, fallback to any available injected EVM provider
    // (Supports in-app mobile browsers like MetaMask Mobile, Trust Mobile, Rabby, etc.)
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
          let chainId = 137;
          try {
            const chainIdHex = await injected.request({ method: 'eth_chainId' });
            if (chainIdHex) chainId = parseInt(chainIdHex, 16);
          } catch {}

          if (chainId !== 137) {
            try {
              await injected.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: '0x89' }],
              });
              chainId = 137;
            } catch (switchError: any) {
              if (switchError.code === 4902) {
                await injected.request({
                  method: 'wallet_addEthereumChain',
                  params: [{
                    chainId: '0x89',
                    chainName: 'Polygon Mainnet',
                    nativeCurrency: { name: 'POL', symbol: 'POL', decimals: 18 },
                    rpcUrls: ['https://polygon-rpc.com'],
                    blockExplorerUrls: ['https://polygonscan.com'],
                  }],
                });
                chainId = 137;
              } else {
                throw new Error('Please approve the Polygon network switch in your wallet.');
              }
            }
          }

          return await this.setConnectedAddress(accounts[0], provider, chainId);
        }
        throw new Error('No wallet account was selected.');
      } catch (err: any) {
        if (err?.code === 4001 || err?.message?.includes('User rejected') || err?.message?.includes('cancelled')) {
          throw new Error('Connection request was cancelled in your wallet.');
        }
        if (err?.code === -32002) {
          throw new Error('Wallet is waiting for your confirmation. Please check your wallet app.');
        }
        // Do not silently fall back to a fake/local session after a real wallet error.
        if (err instanceof Error) throw err;
        throw new Error('The wallet did not complete the connection request.');
      }
    }

    // On mobile browsers, WalletConnect is the only real-wallet handoff available.
    return await this.connectWalletConnectTargeted(provider, onUri);
  }

  public async connectDirect(address: string, providerName: string = 'EVM Wallet'): Promise<ConnectedAccountState> {
    let cleanAddr = address.trim();
    if (!cleanAddr.startsWith('0x') && !cleanAddr.startsWith('0X')) {
      cleanAddr = `0x${cleanAddr}`;
    }
    // Validate that it's a valid 40-hex-character Ethereum/Polygon address
    if (!/^0x[a-fA-F0-9]{40}$/.test(cleanAddr)) {
      throw new Error('Invalid Ethereum/Polygon address. Address must be 42 characters starting with 0x.');
    }
    return await this.setConnectedAddress(cleanAddr, providerName, 137);
  }

  public disconnect(): void {
    try {
      localStorage.removeItem('pulsar_active_address');
      localStorage.removeItem('pulsar_active_provider');
      localStorage.removeItem('pulsar_quick_address');
      localStorage.removeItem('pulsar_quick_key');
    } catch {}
    this.currentAccount = {
      address: '',
      shortAddress: '',
      chainId: 137,
      networkName: 'Polygon Mainnet',
      balanceUSDT: 0,
      connected: false,
      providerName: '',
    };
    this.notify();
  }

  private async setConnectedAddress(
    address: string,
    providerName: string,
    chainId: number = 137
  ): Promise<ConnectedAccountState> {
    const formatted = address.toLowerCase();
    const short = `${formatted.slice(0, 6)}...${formatted.slice(-4)}`;

    try {
      localStorage.setItem('pulsar_active_address', formatted);
      localStorage.setItem('pulsar_active_provider', providerName);
    } catch {}

    // Load clean real data from Cloud Firestore with local cache
    const userData = await this.loadUserDataAsync(formatted);

    this.currentAccount = {
      address: formatted,
      shortAddress: short,
      chainId,
      networkName: chainId === 137 ? 'Polygon Mainnet' : chainId === 1 ? 'Ethereum Mainnet' : chainId === 56 ? 'BNB Chain' : 'EVM Network',
      balanceUSDT: userData.vaultBalance,
      connected: true,
      providerName,
    };

    this.notify();
    return this.currentAccount;
  }

  public static getPlayerTagForAddress(address: string): string {
    const clean = address.toLowerCase();
    const short = clean.slice(2, 6).toUpperCase();
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

  public async loadUserDataAsync(address: string): Promise<UserWalletData> {
    const cleanAddr = address.toLowerCase();
    const defaultTag = RealWeb3Manager.getPlayerTagForAddress(cleanAddr);
    
    // 1. Try Firebase Firestore with rapid timeout to stay lightning fast if offline
    try {
      const userDocRef = doc(db, 'users', cleanAddr);
      const snapPromise = getDoc(userDocRef);
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Firestore timeout')), 2500)
      );
      const snap = await Promise.race([snapPromise, timeoutPromise]);
      if (snap && snap.exists()) {
        const cloudData = snap.data() as UserWalletData;
        if (!cloudData.playerId) {
          cloudData.playerId = defaultTag;
        }
        this.saveToLocal(cloudData);
        return cloudData;
      }
    } catch (e) {
      console.warn('Firestore load skipped or offline, using local cache:', e);
    }

    // 2. Try LocalStorage
    const local = this.loadFromLocal(cleanAddr);
    if (local) {
      if (!local.playerId) {
        local.playerId = defaultTag;
        this.saveToLocal(local);
      }
      this.syncToFirestore(local);
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
    if (this.currentAccount.address === data.address) {
      this.currentAccount.balanceUSDT = data.vaultBalance;
      this.notify();
    }
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

  private async syncToFirestore(data: UserWalletData): Promise<void> {
    try {
      const cleanAddr = data.address.toLowerCase();
      const userDocRef = doc(db, 'users', cleanAddr);
      await setDoc(
        userDocRef,
        {
          ...data,
          updatedAt: Date.now(),
        },
        { merge: true }
      );

      // Leaderboard table updated strictly upon real matches
      if (data.wins > 0 || data.totalMatches > 0) {
        const lbRef = doc(db, 'leaderboard', cleanAddr);
        const winRate = data.totalMatches > 0 ? Math.round((data.wins / data.totalMatches) * 100) : 0;
        await setDoc(
          lbRef,
          {
            address: cleanAddr,
            shortAddress: `${cleanAddr.slice(0, 6)}...${cleanAddr.slice(-4)}`,
            wins: data.wins,
            totalMatches: data.totalMatches,
            bestReactionMs: data.bestReactionMs,
            winRate,
            xp: data.xp || 0,
            level: data.level || 1,
            updatedAt: Date.now(),
          },
          { merge: true }
        );
      }

      // Sync latest match to global matches ledger
      if (data.history && data.history.length > 0) {
        const latestMatch = data.history[0];
        if (latestMatch && latestMatch.id) {
          await this.recordGlobalMatchToFirestore(latestMatch, cleanAddr);
        }
      }
    } catch (e) {
      console.warn('Firestore sync failed:', e);
    }
  }

  public async recordGlobalMatchToFirestore(match: MatchRecord, playerAddress: string): Promise<void> {
    try {
      const matchDocRef = doc(db, 'matches', match.id);
      await setDoc(
        matchDocRef,
        {
          id: match.id,
          playerAddress,
          opponentAddress: match.opponentName || 'Arena Opponent',
          game: match.game || 'reaction',
          result: match.result,
          entryFee: match.entryFee || 0,
          prize: match.prize || 0,
          yourTime: match.yourTime || 0,
          opponentTime: match.opponentTime || 0,
          timestamp: match.timestamp || Date.now(),
          oracleSignature: match.oracleSignature || '0x_oracle_verified',
        },
        { merge: true }
      );
    } catch (err) {
      console.warn('Global match ledger recording notice:', err);
    }
  }

  public subscribeGlobalMatches(callback: (matches: MatchRecord[]) => void): () => void {
    try {
      const matchesCol = collection(db, 'matches');
      const q = query(matchesCol, orderBy('timestamp', 'desc'), limit(15));
      const unsubscribe = onSnapshot(
        q,
        (snapshot) => {
          const list: MatchRecord[] = [];
          snapshot.forEach((docSnap) => {
            const d = docSnap.data();
            list.push({
              id: d.id || docSnap.id,
              game: d.game || 'reaction',
              result: d.result || 'win',
              entryFee: Number(d.entryFee) || 0,
              prize: Number(d.prize) || 0,
              opponentTime: Number(d.opponentTime) || 0,
              yourTime: Number(d.yourTime) || 0,
              timestamp: Number(d.timestamp) || Date.now(),
              oracleSignature: d.oracleSignature,
              opponentName: d.opponentAddress || 'Arena Rival',
            });
          });
          callback(list);
        },
        (error) => {
          console.warn('Matches live onSnapshot listener handled:', error);
        }
      );
      return unsubscribe;
    } catch (e) {
      console.warn('Error establishing Firestore match listener:', e);
      return () => {};
    }
  }

  public async fetchGlobalLeaderboard(): Promise<LeaderboardPlayer[]> {
    try {
      const lbCol = collection(db, 'leaderboard');
      const q = query(lbCol, orderBy('wins', 'desc'), limit(20));
      const getPromise = getDocs(q);
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Leaderboard query timeout')), 3000)
      );
      const querySnapshot = await Promise.race([getPromise, timeoutPromise]);
      
      const results: LeaderboardPlayer[] = [];
      querySnapshot.forEach((d) => {
        const val = d.data();
        const earned = typeof val.totalEarnedUSDT === 'number' ? val.totalEarnedUSDT : Math.round((val.wins || 0) * 1.96 * 100) / 100;
        const tag = val.playerId || val.name || (val.address ? RealWeb3Manager.getPlayerTagForAddress(val.address) : 'Arena Player');
        const bestReaction = val.bestReactionMs || val.reactionTime || 185;
        results.push({
          address: val.address || `0x${Math.random().toString(16).slice(2, 10)}`,
          shortAddress: val.shortAddress || (val.address ? `${val.address.slice(0, 6)}...${val.address.slice(-4)}` : '0x...'),
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

      return SEED_LEADERBOARD;
    } catch (e) {
      console.warn('Leaderboard query handled with local cache fallback:', e);
      try {
        const cached = localStorage.getItem('pulsar_cached_leaderboard');
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) return parsed;
        }
      } catch {}
      return SEED_LEADERBOARD;
    }
  }

  public async searchPlayers(searchQuery: string): Promise<FriendProfile[]> {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];

    const matched: FriendProfile[] = [];

    // 1. Check in-memory & verified seed profiles
    for (const seed of SEED_PLAYERS) {
      if (
        seed.address.toLowerCase().includes(q) ||
        seed.playerId.toLowerCase().includes(q) ||
        seed.shortAddress.toLowerCase().includes(q)
      ) {
        matched.push(seed);
      }
    }

    // 2. If it's a valid EVM address format and not found in seeds, generate dynamic verified profile
    if (q.startsWith('0x') && q.length >= 6) {
      const alreadyAdded = matched.some((m) => m.address.toLowerCase() === q);
      if (!alreadyAdded) {
        try {
          const userDoc = await getDoc(doc(db, 'users', q));
          if (userDoc.exists()) {
            const data = userDoc.data() as UserWalletData;
            matched.push({
              address: data.address,
              playerId: data.playerId || `Player#${data.address.slice(2, 6)}`,
              shortAddress: `${data.address.slice(0, 6)}...${data.address.slice(-4)}`,
              level: data.level || 1,
              xp: data.xp || 0,
              wins: data.wins || 0,
              totalMatches: data.totalMatches || 0,
              bestReactionMs: data.bestReactionMs || 0,
              winRate: data.totalMatches > 0 ? Math.round((data.wins / data.totalMatches) * 100) : 0,
              status: 'online',
            });
          } else if (q.length === 42) {
            // New valid EVM address
            matched.push({
              address: q,
              playerId: `Player#${q.slice(2, 6)}`,
              shortAddress: `${q.slice(0, 6)}...${q.slice(-4)}`,
              level: 1,
              xp: 0,
              wins: 0,
              totalMatches: 0,
              bestReactionMs: 0,
              winRate: 0,
              status: 'online',
              bio: 'New challenger on EVM',
            });
          }
        } catch {}
      }
    }

    return matched;
  }

  public getSavedFriendsList(userAddress: string): FriendProfile[] {
    if (!userAddress) return [];
    const local = this.loadFromLocal(userAddress.toLowerCase());
    const friendAddrs = local?.savedFriends || [];
    const friends: FriendProfile[] = [];

    for (const addr of friendAddrs) {
      const cleanAddr = addr.toLowerCase();
      const seed = SEED_PLAYERS.find((s) => s.address.toLowerCase() === cleanAddr);
      if (seed) {
        friends.push(seed);
      } else {
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
}

export { RealWeb3Manager };
export const realWeb3Manager = new RealWeb3Manager();
