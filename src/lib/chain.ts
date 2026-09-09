/**
 * PULSAR — Single Source of Truth for Chain & Contract Configuration
 * ------------------------------------------------------------------
 * ONE file defines the network, token, and escrow settings. No parallel
 * configs. All values are env-driven; hardcoded values are explicitly
 * flagged as UNVERIFIED until confirmed on Polygonscan.
 *
 * Client-exposed vars must be VITE_-prefixed. The oracle signing secret
 * is server-only (api/) and must NEVER appear in client code.
 */

export const CHAIN = {
  chainId: 137,
  chainHex: '0x89',
  name: 'Polygon Mainnet',
  currency: 'POL',
  rpcUrls: ['https://polygon-bor-rpc.publicnode.com', 'https://1rpc.io/matic', 'https://polygon-rpc.com'],
  explorerUrl: 'https://polygonscan.com',
} as const;

export const TOKENS = {
  // Canonical Polygon PoS USDT (6 decimals)
  USDT: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
  USDT_DECIMALS: 6,
} as const;

const env = (typeof import.meta !== 'undefined' ? (import.meta as any).env ?? {} : {}) as Record<string, string | undefined>;

function resolveConfigured(kind: 'escrow' | 'treasury' | 'oracle', envKey: string, hardcoded: string) {
  const fromEnv = env[envKey]?.trim();
  if (fromEnv && /^0x[a-fA-F0-9]{40}$/.test(fromEnv)) {
    return { address: fromEnv, source: 'env' as const, verified: false };
  }
  if (hardcoded && /^0x[a-fA-F0-9]{40}$/.test(hardcoded)) {
    return { address: hardcoded, source: 'hardcoded' as const, verified: false };
  }
  return { address: '', source: 'unset' as const, verified: false };
}

/**
 * Escrow deployment. The hardcoded address below was found in the legacy
 * config and is treated as UNVERIFIED. Confirm it on Polygonscan, then set
 * VITE_ESCROW_ADDRESS (env wins over this fallback).
 */
export const ESCROW = resolveConfigured(
  'escrow',
  'VITE_ESCROW_ADDRESS',
  '0xac92cb9f43ca51bd723692932bc4f979ea2e3aef'
);

/** Platform treasury — receives the 2% rake. Set VITE_TREASURY_WALLET_ADDRESS. */
export const TREASURY = resolveConfigured(
  'treasury',
  'VITE_TREASURY_WALLET_ADDRESS',
  '0x0B7533FA9f95D21962fae73962b214dB67F8ec89'
);

/** Oracle signer — verifies settleDuel signatures. Set VITE_ORACLE_WALLET_ADDRESS. */
export const ORACLE_SIGNER = resolveConfigured(
  'oracle',
  'VITE_ORACLE_WALLET_ADDRESS',
  '0x884179C3B577025abEFEfF6694aA2AFc652716da'
);

export const ECONOMY = {
  /** Platform rake in basis points — must match contract PLATFORM_FEE_BPS (200 = 2%). */
  platformFeeBps: 200,
  /** Winner receives totalPool minus rake. UI copy must always derive from this. */
  winnerShareBps: 10_000 - 200,
} as const;

/**
 * Escrow ABI — mirrors contracts/PulsarEscrow.sol exactly (settleDuel(Proof)).
 * Do not edit here without editing the Solidity source; they are one contract.
 */
export const PULSAR_ESCROW_ABI = [
  'function createDuel(bytes32 matchId, uint256 stakeAmount) external',
  'function joinDuel(bytes32 matchId) external',
  'function settleDuel((bytes32 matchId, address winner, uint256 winnerTimeMs, uint256 loserTimeMs, uint256 nonce, uint256 deadline, bytes signature) proof) external',
  'function refundTimeoutMatch(bytes32 matchId) external',
  'function matches(bytes32) view returns (bytes32 matchId, address player1, address player2, uint256 stakeAmount, uint256 totalPool, uint256 createdAt, uint8 status, address winner, uint256 winnerReactionMs, uint256 loserReactionMs)',
  'function paymentToken() view returns (address)',
  'function treasuryWallet() view returns (address)',
  'function oracleSigner() view returns (address)',
  'function totalDuelsSettled() view returns (uint256)',
  'function totalVolumeDistributed() view returns (uint256)',
  'event MatchCreated(bytes32 indexed matchId, address indexed player1, uint256 stakeAmount, uint256 totalPool)',
  'event MatchJoined(bytes32 indexed matchId, address indexed player2)',
  'event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizePaid, uint256 platformFee)',
  'event MatchCancelled(bytes32 indexed matchId, string reason)',
  'event MatchRefunded(bytes32 indexed matchId, uint256 refundPerPlayer)',
] as const;

export const ERC20_ABI = [
  'function balanceOf(address) view returns (uint256)',
  'function allowance(address owner, address spender) view returns (uint256)',
  'function approve(address spender, uint256 value) returns (bool)',
] as const;

/** Honest state helper: is real-money play actually wired up? */
export function isEscrowConfigured(): boolean {
  return ESCROW.source !== 'unset' && TREASURY.source !== 'unset' && ORACLE_SIGNER.source !== 'unset';
}

export function explorerAddressUrl(address: string): string {
  return `${CHAIN.explorerUrl}/address/${address}`;
}

export function explorerTxUrl(txHash: string): string {
  return `${CHAIN.explorerUrl}/tx/${txHash}`;
}
