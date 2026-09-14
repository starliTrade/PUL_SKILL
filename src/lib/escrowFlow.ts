/**
 * P1.15 — REAL on-chain escrow flow. This is the only file allowed to move
 * money. Every function returns a REAL transaction hash or throws — nothing
 * here fabricates success. UI must surface thrown errors verbatim.
 *
 * Flow: approve → createDuel → joinDuel → (server settle) → settleDuel(proof)
 * Balances shown in the app come from the chain, not from a database number.
 */

import { BrowserProvider, Contract, formatUnits, parseUnits } from 'ethers';
import { CHAIN, TOKENS, PULSAR_ESCROW_ABI, ERC20_ABI, ESCROW, isPaymentTokenConfigured } from './chain';

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

function requireInjected(): BrowserProvider {
  const eth = (window as any).ethereum;
  if (!eth) throw new Error('No injected wallet found. Connect a wallet first.');
  return new BrowserProvider(eth, CHAIN.chainId);
}

/**
 * H5 — chain-guard for MONEY transactions. ethers' BrowserProvider does NOT
 * force the wallet's active chain: a wallet left on Ethereum mainnet happily
 * signs an `approve` for the escrow address ON THE WRONG CHAIN (EVM address
 * space is shared across chains, so same-address contract collisions are a
 * real phishing vector). Every money-moving flow calls this first; it reads
 * eth_chainId and triggers wallet_switchEthereumChain when the wallet is
 * elsewhere.
 */
async function ensureCorrectChain(): Promise<void> {
  const eth = (window as any).ethereum;
  if (!eth) throw new Error('No injected wallet found. Connect a wallet first.');
  let current: string;
  try {
    current = (await eth.request({ method: 'eth_chainId' })) as string;
  } catch {
    throw new Error('Could not read the connected chain from your wallet.');
  }
  if (BigInt(current) === BigInt(CHAIN.chainId)) return;
  try {
    await eth.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: '0x' + BigInt(CHAIN.chainId).toString(16) }],
    });
  } catch (err: unknown) {
    const code = (err as { code?: number })?.code;
    if (code === 4902) {
      throw new Error(
        `This network (chain ${CHAIN.chainId}) is not added to your wallet yet. Add it and retry.`,
      );
    }
    throw new Error('Wrong network — switch your wallet to the app network and retry.');
  }
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

export async function getUsdtBalance(address: string): Promise<string> {
  const provider = requireInjected();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.balanceOf(address);
  return formatUnits(raw, TOKENS.USDT_DECIMALS);
}

export async function getAllowance(owner: string): Promise<string> {
  const provider = requireInjected();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.allowance(owner, requireEscrowAddress());
  return formatUnits(raw, TOKENS.USDT_DECIMALS);
}

/** ERC-20 approve for the escrow to pull `stakeUsdt`. Returns real tx hash. */
export async function approveUsdt(stakeUsdt: number): Promise<string> {
  await ensureCorrectChain(); // H5: never sign an approve on the wrong chain
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), TOKENS.USDT_DECIMALS);
  const tx = await token.approve(requireEscrowAddress(), amount);
  await tx.wait();
  return tx.hash as string;
}

/** Player 1 locks their stake into a new duel. Returns real tx hash. */
export async function createDuel(matchIdBytes32: string, stakeUsdt: number): Promise<string> {
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), TOKENS.USDT_DECIMALS);
  const tx = await escrow.createDuel(matchIdBytes32, amount);
  await tx.wait();
  return tx.hash as string;
}

/** Player 2 locks the matching stake. Returns real tx hash. */
export async function joinDuel(matchIdBytes32: string): Promise<string> {
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
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
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
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
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
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
  winner: string;
}> {
  const provider = requireInjected();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, provider);
  const m = await escrow.matches(matchIdBytes32);
  return {
    status: Number(m.status),
    player1: m.player1,
    player2: m.player2,
    stakeAmount: m.stakeAmount,
    totalPool: m.totalPool,
    winner: m.winner,
  };
}
