/**
 * P1.15 — REAL on-chain escrow flow. This is the only file allowed to move
 * money. Every function returns a REAL transaction hash or throws — nothing
 * here fabricates success. UI must surface thrown errors verbatim.
 *
 * Flow: approve → createDuel → joinDuel → (server settle) → settleDuel(proof)
 * Balances shown in the app come from the chain, not from a database number.
 */

import { BrowserProvider, Contract, formatUnits, parseUnits } from 'ethers';
import {
  CHAIN,
  TOKENS,
  PULSAR_ESCROW_ABI,
  ERC20_ABI,
  ESCROW,
  TREASURY,
  ORACLE_SIGNER,
  isPaymentTokenConfigured,
  isEscrowConfigured,
} from './chain';
import { realWeb3Manager } from './realWeb3';

export interface EscrowStatus {
  configured: boolean;
  escrowAddress: string;
  message: string;
}

export function escrowStatus(): EscrowStatus {
  if (!ESCROW.address) {
    return {
      configured: false,
      escrowAddress: '',
      message: 'Escrow contract address is not configured (VITE_ESCROW_ADDRESS).',
    };
  }
  if (!isPaymentTokenConfigured()) {
    return {
      configured: false,
      escrowAddress: ESCROW.address,
      message: 'Payment token is not configured for this chain (set VITE_PAYMENT_TOKEN_ADDRESS on testnet).',
    };
  }
  return {
    configured: true,
    escrowAddress: ESCROW.address,
    message: `Escrow ${ESCROW.source}: ${ESCROW.address}`,
  };
}

function requireActiveProvider(): BrowserProvider {
  const provider = realWeb3Manager.getActiveEip1193Provider();
  if (!provider) throw new Error('No active wallet provider found. Connect a wallet first.');
  return new BrowserProvider(provider, CHAIN.chainId);
}

function requireEscrowAddress(): string {
  if (!ESCROW.address) {
    throw new Error('Escrow address is not configured. Real-money play is disabled.');
  }
  if (!isPaymentTokenConfigured()) {
    throw new Error('Payment token is not configured for this chain. Real-money play is disabled.');
  }
  return ESCROW.address;
}

/** Fail before matchmaking if frontend configuration does not describe the
 * deployed contract. This prevents pairing an opponent and only then finding
 * that funds would be sent to the wrong token/oracle deployment. */
export async function validateEscrowDeployment(): Promise<void> {
  if (!isEscrowConfigured() || !isPaymentTokenConfigured()) {
    throw new Error('Escrow, token, treasury, and oracle addresses must all be configured.');
  }
  const provider = requireActiveProvider();
  const network = await provider.getNetwork();
  if (Number(network.chainId) !== CHAIN.chainId) {
    throw new Error(`Wallet is on chain ${network.chainId}; switch to ${CHAIN.name}.`);
  }
  const escrowAddress = requireEscrowAddress();
  if ((await provider.getCode(escrowAddress)) === '0x') {
    throw new Error('No escrow contract is deployed at VITE_ESCROW_ADDRESS on this chain.');
  }
  const escrow = new Contract(escrowAddress, PULSAR_ESCROW_ABI, provider);
  const [paymentToken, treasury, oracle] = await Promise.all([
    escrow.paymentToken(),
    escrow.treasuryWallet(),
    escrow.oracleSigner(),
  ]);
  const same = (left: string, right: string) => left.toLowerCase() === right.toLowerCase();
  if (!same(paymentToken, TOKENS.USDT)) throw new Error('Configured payment token does not match the escrow contract.');
  if (!same(treasury, TREASURY.address)) throw new Error('Configured treasury does not match the escrow contract.');
  if (!same(oracle, ORACLE_SIGNER.address)) throw new Error('Configured oracle does not match the escrow contract.');
}

export async function getUsdtBalance(address: string): Promise<string> {
  const provider = requireActiveProvider();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.balanceOf(address);
  return formatUnits(raw, TOKENS.USDT_DECIMALS);
}

export async function getAllowance(owner: string): Promise<string> {
  const provider = requireActiveProvider();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.allowance(owner, requireEscrowAddress());
  return formatUnits(raw, TOKENS.USDT_DECIMALS);
}

/** ERC-20 approve for the escrow to pull `stakeUsdt`. Returns real tx hash. */
export async function approveUsdt(stakeUsdt: number): Promise<string> {
  const provider = requireActiveProvider();
  const signer = await provider.getSigner();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), TOKENS.USDT_DECIMALS);
  const tx = await token.approve(requireEscrowAddress(), amount);
  await tx.wait();
  return tx.hash as string;
}

/** Player 1 locks their stake into a new duel. Returns real tx hash. */
export async function createDuel(matchIdBytes32: string, stakeUsdt: number, expectedPlayer2: string): Promise<string> {
  const provider = requireActiveProvider();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), TOKENS.USDT_DECIMALS);
  const tx = await escrow.createDuel(matchIdBytes32, amount, expectedPlayer2);
  await tx.wait();
  return tx.hash as string;
}

/** Player 2 locks the matching stake. Returns real tx hash. */
export async function joinDuel(matchIdBytes32: string): Promise<string> {
  const provider = requireActiveProvider();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const tx = await escrow.joinDuel(matchIdBytes32);
  await tx.wait();
  return tx.hash as string;
}

export interface SettlementProof {
  matchId: string;          // bytes32 hex
  winner: string;
  winnerTimeMs: number;
  loserTimeMs: number;
  nonce: string;            // uint256 as string (JS-safe)
  deadline: number;         // unix seconds
  signature: string;        // 0x… 65 bytes, low-s
}

/** Submit the server-signed proof to release the pot. Returns real tx hash. */
export async function settleDuel(proof: SettlementProof): Promise<string> {
  const provider = requireActiveProvider();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const tx = await escrow.settleDuel({
    matchId: proof.matchId,
    winner: proof.winner,
    winnerTimeMs: proof.winnerTimeMs,
    loserTimeMs: proof.loserTimeMs,
    nonce: proof.nonce,
    deadline: proof.deadline,
    signature: proof.signature,
  });
  await tx.wait();
  return tx.hash as string;
}

/** Anyone can trigger a timeout refund after MATCH_TIMEOUT. */
export async function refundTimeoutMatch(matchIdBytes32: string): Promise<string> {
  const provider = requireActiveProvider();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const tx = await escrow.refundTimeoutMatch(matchIdBytes32);
  await tx.wait();
  return tx.hash as string;
}

/** Read a duel's on-chain state (status: 0 None, 1 Created, 2 Active, 3 Settled, 4 Cancelled, 5 Refunded). */
export async function getDuelState(matchIdBytes32: string): Promise<{
  status: number;
  player1: string;
  player2: string;
  stakeAmount: bigint;
  totalPool: bigint;
  createdAt: bigint;
  winner: string;
}> {
  const provider = requireActiveProvider();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, provider);
  const m = await escrow.matches(matchIdBytes32);
  return {
    status: Number(m.status),
    player1: m.player1,
    player2: m.player2,
    stakeAmount: m.stakeAmount,
    totalPool: m.totalPool,
    createdAt: m.createdAt,
    winner: m.winner,
  };
}

/** Idempotently fund the matched duel and wait until both deposits are on
 * chain. Safe across page refreshes: already-created/already-active duels are
 * validated and resumed instead of submitting duplicate transactions. */
export async function ensureDuelActive(
  matchIdBytes32: string,
  stakeUsdt: number,
  currentAddress: string,
  opponentAddress: string,
  isCreator: boolean
): Promise<void> {
  await validateEscrowDeployment();
  const me = currentAddress.toLowerCase();
  const opponent = opponentAddress.toLowerCase();
  const expectedPlayer1 = isCreator ? me : opponent;
  const expectedPlayer2 = isCreator ? opponent : me;
  const expectedStake = parseUnits(String(stakeUsdt), TOKENS.USDT_DECIMALS);
  const deadline = Date.now() + 120_000;

  const validateExisting = (state: Awaited<ReturnType<typeof getDuelState>>) => {
    if (state.status === 0) return;
    if (state.player1.toLowerCase() !== expectedPlayer1 || state.player2.toLowerCase() !== expectedPlayer2) {
      throw new Error('On-chain duel participants do not match the server match.');
    }
    if (state.stakeAmount !== expectedStake || state.totalPool !== expectedStake * 2n) {
      throw new Error('On-chain duel stake does not match the server match.');
    }
    if (state.status > 2) throw new Error('This on-chain duel is already closed.');
  };

  let state = await getDuelState(matchIdBytes32);
  validateExisting(state);

  if (isCreator && state.status === 0) {
    await approveUsdt(stakeUsdt);
    await createDuel(matchIdBytes32, stakeUsdt, opponentAddress);
    state = await getDuelState(matchIdBytes32);
    validateExisting(state);
  }

  while (!isCreator && state.status === 0 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    state = await getDuelState(matchIdBytes32);
    validateExisting(state);
  }

  if (!isCreator && state.status === 1) {
    await approveUsdt(stakeUsdt);
    await joinDuel(matchIdBytes32);
    state = await getDuelState(matchIdBytes32);
    validateExisting(state);
  }

  while (state.status !== 2 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    state = await getDuelState(matchIdBytes32);
    validateExisting(state);
  }
  if (state.status !== 2) {
    throw new Error('Both escrow deposits were not confirmed within two minutes.');
  }
}
