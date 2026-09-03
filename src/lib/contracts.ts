/**
 * Pulsar Smart Contracts Configuration & ABI Definitions
 * Polygon Mainnet (Chain ID 137) & Multi-EVM Architecture
 */

export const PULSAR_CONTRACT_CONFIG = {
  // Polygon Mainnet (Chain ID 137)
  network: {
    chainId: 137,
    name: 'Polygon Mainnet',
    rpcUrl: 'https://polygon-rpc.com',
    blockExplorer: 'https://polygonscan.com',
  },

  // Token Addresses
  tokens: {
    // Polygon Mainnet USDT (PoS)
    USDT: '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
    // Polygon Mainnet USDC
    USDC: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359',
  },

  // Escrow Deployment Target
  escrow: {
    address: '0x27C17a42E4cb04C0567e6fe84594A1a76C291566',
    platformFeeBps: 200, // 2%
  },
};

export const PULSAR_ESCROW_ABI = [
  "function createDuel(bytes32 matchId, uint256 stakeAmount) external",
  "function joinDuel(bytes32 matchId) external",
  "function settleDuel((bytes32 matchId, address winner, uint256 winnerTimeMs, uint256 loserTimeMs, uint256 nonce, bytes signature) proof) external",
  "function refundTimeoutMatch(bytes32 matchId) external",
  "function matches(bytes32) external view returns (bytes32 matchId, address player1, address player2, uint256 stakeAmount, uint256 totalPool, uint256 createdAt, uint8 status, address winner, uint256 winnerReactionMs, uint256 loserReactionMs)",
  "function treasuryWallet() external view returns (address)",
  "function oracleSigner() external view returns (address)",
  "event MatchCreated(bytes32 indexed matchId, address indexed player1, uint256 stakeAmount, uint256 totalPool)",
  "event MatchJoined(bytes32 indexed matchId, address indexed player2)",
  "event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizePaid, uint256 platformFee)"
];

export const ERC20_ABI = [
  "function name() view returns (string)",
  "function symbol() view returns (string)",
  "function decimals() view returns (uint8)",
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function approve(address spender, uint256 value) returns (bool)",
  "function transfer(address to, uint256 value) returns (bool)",
  "function transferFrom(address from, address to, uint256 value) returns (bool)",
  "event Transfer(address indexed from, address indexed to, uint256 value)",
  "event Approval(address indexed owner, address indexed spender, uint256 value)"
];
