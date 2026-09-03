import { ethersLikeHash } from './cryptoUtils';

export interface NetworkConfig {
  chainId: number;
  chainHex: string;
  name: string;
  currency: string;
  rpcUrl: string;
  explorerUrl: string;
  escrowContractAddress: string;
  usdtTokenAddress: string;
  faucetUrl: string;
}

export const SUPPORTED_NETWORKS: Record<string, NetworkConfig> = {
  polygonAmoy: {
    chainId: 80002,
    chainHex: '0x13882',
    name: 'Polygon Amoy Testnet (Zero Cost)',
    currency: 'POL',
    rpcUrl: 'https://rpc-amoy.polygon.technology',
    explorerUrl: 'https://amoy.polygonscan.com',
    escrowContractAddress: '0x8b32A46A92e105Ec64dB1A7036a1476bF79E89D1',
    usdtTokenAddress: '0x32A47A3dBb68D4b9F7e85c1a79cD148a04E38799',
    faucetUrl: 'https://faucet.polygon.technology',
  },
  arbitrumSepolia: {
    chainId: 421614,
    chainHex: '0x66eee',
    name: 'Arbitrum Sepolia (Zero Cost)',
    currency: 'ETH',
    rpcUrl: 'https://sepolia-rollup.arbitrum.io/rpc',
    explorerUrl: 'https://sepolia.arbiscan.io',
    escrowContractAddress: '0x5C6bA79E89D1a7036a1476bF79E89D18b32A46A9',
    usdtTokenAddress: '0x7e85c1a79cD148a04E3879932A47A3dBb68D4b9F',
    faucetUrl: 'https://faucet.quicknode.com/arbitrum/sepolia',
  },
  baseSepolia: {
    chainId: 84532,
    chainHex: '0x14a34',
    name: 'Base Sepolia (Coinbase L2)',
    currency: 'ETH',
    rpcUrl: 'https://sepolia.base.org',
    explorerUrl: 'https://sepolia.basescan.org',
    escrowContractAddress: '0x1A7036a1476bF79E89D18b32A46A92e105Ec64dB',
    usdtTokenAddress: '0x04E3879932A47A3dBb68D4b9F7e85c1a79cD148a',
    faucetUrl: 'https://www.coinbase.com/faucets/base-ethereum-sepolia-faucet',
  },
};

export const PULSAR_ESCROW_ABI = [
  'function depositVault(uint256 amount) external',
  'function withdrawVault(uint256 amount) external',
  'function createMatchEscrow(bytes32 matchId, address playerB, uint256 entryFee) external',
  'function settleMatchWithOracle(bytes32 matchId, address playerA, address playerB, address winner, uint256 entryFee, uint256 prizeAmount, uint256 rakeFee, uint256 nonce, uint256 deadline, bytes calldata signature) external',
  'function emergencyRefund(bytes32 matchId) external',
  'function playerVault(address) external view returns (uint256)',
  'function oracleSigner() external view returns (address)',
  'function treasuryWallet() external view returns (address)',
  'function RAKE_BPS() external view returns (uint256)',
  'event MatchCreated(bytes32 indexed matchId, address indexed playerA, address indexed playerB, uint256 entryFee, uint256 totalPool)',
  'event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizeAmount, uint256 rakeFee)',
  'event MatchRefunded(bytes32 indexed matchId, string reason)',
];

export class Web3Service {
  public activeNetwork: NetworkConfig = SUPPORTED_NETWORKS.polygonAmoy;

  public hasInjectedWallet(): boolean {
    return typeof window !== 'undefined' && typeof (window as any).ethereum !== 'undefined';
  }

  public async connectInjectedWallet(): Promise<{ address: string; chainId: number } | null> {
    if (!this.hasInjectedWallet()) return null;
    try {
      const ethereum = (window as any).ethereum;
      const accounts = await ethereum.request({ method: 'eth_requestAccounts' });
      const chainIdHex = await ethereum.request({ method: 'eth_chainId' });
      const chainId = parseInt(chainIdHex, 16);
      return {
        address: accounts[0],
        chainId,
      };
    } catch (err) {
      console.warn('Injected wallet connection failed or rejected:', err);
      return null;
    }
  }

  public async switchNetwork(networkKey: keyof typeof SUPPORTED_NETWORKS): Promise<boolean> {
    const target = SUPPORTED_NETWORKS[networkKey];
    if (!target) return false;
    this.activeNetwork = target;

    if (!this.hasInjectedWallet()) return true;

    try {
      const ethereum = (window as any).ethereum;
      await ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: target.chainHex }],
      });
      return true;
    } catch (switchError: any) {
      // 4902: Chain not added yet
      if (switchError.code === 4902) {
        try {
          const ethereum = (window as any).ethereum;
          await ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [
              {
                chainId: target.chainHex,
                chainName: target.name,
                nativeCurrency: {
                  name: target.currency,
                  symbol: target.currency,
                  decimals: 18,
                },
                rpcUrls: [target.rpcUrl],
                blockExplorerUrls: [target.explorerUrl],
              },
            ],
          });
          return true;
        } catch {
          return false;
        }
      }
      return false;
    }
  }
}

export const web3Service = new Web3Service();
