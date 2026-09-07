import React, { createContext, useContext, useMemo, useState } from 'react';
import {
  createConfig,
  http,
  WagmiProvider,
  useAccount,
  useConnect,
  useDisconnect,
  useBalance,
  useChainId,
  useSwitchChain,
  useConnections,
  type Connector,
} from 'wagmi';
import { polygon, polygonAmoy, arbitrumSepolia, baseSepolia } from 'wagmi/chains';
import { injected, walletConnect, coinbaseWallet } from 'wagmi/connectors';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { formatUnits, fallback } from 'viem';
import { BrowserProvider, JsonRpcSigner } from 'ethers';

// -----------------------------------------------------------------------------
// 1. WAGMI & VIEM CONFIGURATION
// -----------------------------------------------------------------------------

// Dedicated WalletConnect Project ID from env if supplied
const rawProjectId =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WALLETCONNECT_PROJECT_ID) ||
  '';
const WALLET_CONNECT_PROJECT_ID =
  typeof rawProjectId === 'string' && rawProjectId.trim().length === 32 ? rawProjectId.trim() : '';

export const supportedChains = [polygonAmoy, polygon, arbitrumSepolia, baseSepolia] as const;

// Configure connectors safely without triggering relay 403 on unverified origins
const activeConnectors: any[] = [
  injected({
    shimDisconnect: true,
  }),
];

if (WALLET_CONNECT_PROJECT_ID) {
  activeConnectors.push(
    walletConnect({
      projectId: WALLET_CONNECT_PROJECT_ID,
      showQrModal: true,
      metadata: {
        name: 'PULSAR — Skill Battles',
        description: 'Real-Time Web3 Skill Duels & Wagering Arena',
        url: typeof window !== 'undefined' ? window.location.origin : 'https://pulsar.arena',
        icons: ['https://avatars.githubusercontent.com/u/37784886'],
      },
    })
  );
}

export const wagmiConfig = createConfig({
  chains: supportedChains,
  connectors: activeConnectors,
  transports: {
    [polygonAmoy.id]: fallback([
      http('https://rpc-amoy.polygon.technology'),
      http('https://polygon-amoy-bor-rpc.publicnode.com'),
      http('https://rpc.ankr.com/polygon_amoy'),
    ]),
    [polygon.id]: fallback([
      http('https://polygon-rpc.com'),
      http('https://polygon-bor-rpc.publicnode.com'),
      http('https://rpc.ankr.com/polygon'),
      http('https://1rpc.io/matic'),
    ]),
    [arbitrumSepolia.id]: fallback([
      http('https://sepolia-rollup.arbitrum.io/rpc'),
      http('https://arbitrum-sepolia.blockpi.network/v1/rpc/public'),
    ]),
    [baseSepolia.id]: fallback([
      http('https://sepolia.base.org'),
      http('https://base-sepolia-rpc.publicnode.com'),
    ]),
  },
});

// Create a stable react-query client with optimized caching for Web3
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 10_000,
    },
  },
});

// -----------------------------------------------------------------------------
// 2. TYPES
// -----------------------------------------------------------------------------

export interface Web3State {
  // Account Information
  address?: `0x${string}`;
  shortAddress: string;
  isConnected: boolean;
  isConnecting: boolean;
  isReconnecting: boolean;
  isDisconnected: boolean;
  status: 'connected' | 'reconnecting' | 'connecting' | 'disconnected';

  // Network & Chain
  chainId?: number;
  chain?: typeof supportedChains[number];
  isSupportedChain: boolean;
  supportedChains: typeof supportedChains;
  switchChain: (chainId: number) => Promise<void>;
  isSwitchingChain: boolean;

  // Balance
  balance?: string;
  balanceFormatted: string;
  balanceSymbol: string;
  rawBalance?: bigint;
  isLoadingBalance: boolean;
  refetchBalance: () => void;

  // Connection & Connectors
  connectors: readonly Connector[];
  connect: (connectorId?: string) => Promise<void>;
  disconnect: () => Promise<void>;
  activeConnectorName?: string;

  // Status & Error handling
  error: string | null;
  clearError: () => void;

  // Ethers.js v6 Interoperability
  getEthersProvider: () => Promise<BrowserProvider | null>;
  getEthersSigner: () => Promise<JsonRpcSigner | null>;
}

// -----------------------------------------------------------------------------
// 3. REACT CONTEXT (OPTIONAL CUSTOM LAYER)
// -----------------------------------------------------------------------------

const Web3Context = createContext<Web3State | null>(null);

// -----------------------------------------------------------------------------
// 4. MAIN CUSTOM HOOK: useWeb3
// -----------------------------------------------------------------------------

export function useWeb3(): Web3State {
  const account = useAccount();
  const currentChainId = useChainId();
  const connections = useConnections();
  const { connectors, connectAsync } = useConnect();
  const { disconnectAsync } = useDisconnect();
  const { switchChainAsync, isPending: isSwitchingChain } = useSwitchChain();

  const [customError, setCustomError] = useState<string | null>(null);

  // Read native balance
  const {
    data: balanceData,
    isLoading: isLoadingBalance,
    refetch: refetchBalance,
  } = useBalance({
    address: account.address,
    chainId: currentChainId,
  });

  // Calculate formatted short address (e.g., 0x1234...abcd)
  const shortAddress = useMemo(() => {
    if (!account.address) return '';
    return `${account.address.slice(0, 6)}...${account.address.slice(-4)}`;
  }, [account.address]);

  // Determine current active chain object
  const chain = useMemo(() => {
    return supportedChains.find((c) => c.id === currentChainId);
  }, [currentChainId]);

  const isSupportedChain = useMemo(() => {
    return supportedChains.some((c) => c.id === currentChainId);
  }, [currentChainId]);

  // Connect helper
  const connect = async (connectorId?: string) => {
    setCustomError(null);
    try {
      let targetConnector = connectors.find((c) => c.id === connectorId || c.name.toLowerCase() === connectorId?.toLowerCase());
      if (!targetConnector) {
        // Default to injected or first connector
        targetConnector = connectors.find((c) => c.id === 'injected') || connectors[0];
      }

      if (!targetConnector) {
        throw new Error('No compatible Web3 connector found.');
      }

      await connectAsync({ connector: targetConnector });
    } catch (err: any) {
      const msg = err?.message || 'Failed to connect wallet.';
      setCustomError(msg);
      throw err;
    }
  };

  // Disconnect helper
  const disconnect = async () => {
    setCustomError(null);
    try {
      await disconnectAsync();
    } catch (err: any) {
      setCustomError(err?.message || 'Failed to disconnect wallet.');
    }
  };

  // Switch chain helper
  const handleSwitchChain = async (targetChainId: number) => {
    setCustomError(null);
    try {
      await switchChainAsync({ chainId: targetChainId });
    } catch (err: any) {
      setCustomError(err?.message || `Failed to switch to chain ${targetChainId}.`);
      throw err;
    }
  };

  // Ethers.js v6 Provider helper
  const getEthersProvider = async (): Promise<BrowserProvider | null> => {
    if (typeof window === 'undefined') return null;
    const injectedEth = (window as any).ethereum;
    if (injectedEth) {
      return new BrowserProvider(injectedEth);
    }
    return null;
  };

  // Ethers.js v6 Signer helper
  const getEthersSigner = async (): Promise<JsonRpcSigner | null> => {
    const provider = await getEthersProvider();
    if (!provider) return null;
    try {
      return await provider.getSigner();
    } catch (err) {
      console.warn('[useWeb3] Could not obtain ethers Signer:', err);
      return null;
    }
  };

  const activeConnectorName = connections[0]?.connector?.name || account.connector?.name;

  const formattedBalanceString = useMemo(() => {
    if (!balanceData) return '0.0000';
    try {
      const units = formatUnits(balanceData.value, balanceData.decimals);
      const parsed = parseFloat(units);
      return isNaN(parsed) ? '0.0000' : parsed.toFixed(4);
    } catch {
      return '0.0000';
    }
  }, [balanceData]);

  const balanceFormatted = `${formattedBalanceString} ${balanceData?.symbol || 'POL'}`;

  return {
    // Account details
    address: account.address,
    shortAddress,
    isConnected: account.isConnected,
    isConnecting: account.isConnecting,
    isReconnecting: account.isReconnecting,
    isDisconnected: account.isDisconnected,
    status: account.status,

    // Chain details
    chainId: currentChainId,
    chain,
    isSupportedChain,
    supportedChains,
    switchChain: handleSwitchChain,
    isSwitchingChain,

    // Balance details
    balance: balanceData ? formatUnits(balanceData.value, balanceData.decimals) : undefined,
    balanceFormatted,
    balanceSymbol: balanceData?.symbol || 'POL',
    rawBalance: balanceData?.value,
    isLoadingBalance,
    refetchBalance: () => {
      refetchBalance();
    },

    // Connectors & actions
    connectors,
    connect,
    disconnect,
    activeConnectorName,

    // Error status
    error: customError,
    clearError: () => setCustomError(null),

    // Ethers interop
    getEthersProvider,
    getEthersSigner,
  };
}

// -----------------------------------------------------------------------------
// 5. TOP-LEVEL WEB3 PROVIDER WRAPPER
// -----------------------------------------------------------------------------

interface Web3ProviderProps {
  children: React.ReactNode;
}

export function Web3Provider({ children }: Web3ProviderProps): React.ReactElement {
  return React.createElement(
    WagmiProvider,
    { config: wagmiConfig },
    React.createElement(QueryClientProvider, { client: queryClient }, children)
  );
}

export default useWeb3;
