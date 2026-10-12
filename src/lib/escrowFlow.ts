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

function requireInjected(): BrowserProvider {
  // P0-fix: use the ACTIVE wallet provider (WalletConnect on mobile, injected
  // on desktop) instead of window.ethereum only. Previously a WC-only mobile
  // session could connect + SIWE-sign but never approve/create/settle.
  const active = realWeb3Manager.getActiveEip1193Provider() as any;
  const eth = active || (window as any).ethereum;
  if (!eth) throw new Error('No connected wallet found. Connect a wallet first.');
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
  const active = realWeb3Manager.getActiveEip1193Provider() as any;
  const eth = active || (window as any).ethereum;
  if (!eth) throw new Error('No connected wallet found. Connect a wallet first.');
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

/**
 * decimals() of the payment token, cached per token address (audit H13).
 *
 * The write path used the hard-coded `TOKENS.USDT_DECIMALS` (6) while the read
 * path read the real value, so on any other token the stake was scaled by 10^k
 * in the wrong direction — `createDuel(…, parseUnits("1", 6))` deposits 1e-12
 * tokens on an 18-decimal token while the UI advertises a whole one. The
 * joiner's check used the same constant, so nothing caught it.
 *
 * Cached because it is immutable for a given token and every write needs it.
 */
let _decimalsCache: { token: string; value: number } | null = null;

export async function getTokenDecimals(): Promise<number> {
  const token = TOKENS.USDT;
  if (_decimalsCache && _decimalsCache.token === token) {
    return _decimalsCache.value;
  }
  const provider = requireInjected();
  const contract = new Contract(token, ERC20_ABI, provider);
  const value = Number(await contract.decimals());
  if (!Number.isInteger(value) || value < 0 || value > 36) {
    throw new Error(`The payment token reports an implausible decimals() value: ${value}`);
  }
  _decimalsCache = { token, value };
  return value;
}

/** Test seam: forget the cached decimals. */
export function resetTokenDecimalsCache(): void {
  _decimalsCache = null;
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

// Amoy's RPC nodes enforce a dynamic minimum gas price that spikes far above
// what wallets estimate (observed: node min 25 gwei vs wallet suggestion
// 15 gwei → eth_sendRawTransaction reverted code 32603). Always floor the
// price at 30 gwei so wallet suggestions can never dip below the node floor.
async function safeGasPrice(): Promise<bigint> {
  const FLOOR = parseUnits('30', 'gwei');
  try {
    const fee = await requireInjected().getFeeData();
    const suggested = fee.gasPrice ?? 0n;
    return suggested > FLOOR ? suggested : FLOOR;
  } catch {
    return FLOOR;
  }
}

export async function getUsdtBalance(address: string): Promise<string> {
  const provider = requireInjected();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.balanceOf(address);
  return formatUnits(raw, await getTokenDecimals());
}

export async function getAllowance(owner: string): Promise<string> {
  const provider = requireInjected();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, provider);
  const raw: bigint = await token.allowance(owner, requireEscrowAddress());
  return formatUnits(raw, await getTokenDecimals());
}

/** ERC-20 approve for the escrow to pull `stakeUsdt`. Returns real tx hash. */
export async function approveUsdt(stakeUsdt: number): Promise<string> {
  await ensureCorrectChain(); // H5: never sign an approve on the wrong chain
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const token = new Contract(TOKENS.USDT, ERC20_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), await getTokenDecimals());
  const tx = await token.approve(requireEscrowAddress(), amount, { gasPrice: await safeGasPrice() });
  await tx.wait();
  return tx.hash as string;
}

/** Player 1 locks their stake into a new duel. Returns real tx hash. */
export async function createDuel(matchIdBytes32: string, stakeUsdt: number): Promise<string> {
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const amount = parseUnits(String(stakeUsdt), await getTokenDecimals());
  const tx = await escrow.createDuel(matchIdBytes32, amount, { gasPrice: await safeGasPrice() });
  await tx.wait();
  return tx.hash as string;
}

/** Player 2 locks the matching stake. Returns real tx hash. */
export async function joinDuel(matchIdBytes32: string): Promise<string> {
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const tx = await escrow.joinDuel(matchIdBytes32, { gasPrice: await safeGasPrice() });
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
  }, { gasPrice: await safeGasPrice() });
  await tx.wait();
  return tx.hash as string;
}

/**
 * Read the deferred payout the escrow owes `address` (audit H17b).
 *
 * Audit H17 credits a payout the token refused (Tether blacklist, a paused
 * token, a contract that reverts on receipt) instead of reverting the whole
 * settlement. Without this read, that money is invisible to the player who is
 * owed it.
 */
export async function getPendingWithdrawal(address: string): Promise<string> {
  const provider = requireInjected();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, provider);
  const raw: bigint = await escrow.pendingWithdrawals(address);
  return formatUnits(raw, await getTokenDecimals());
}

/**
 * Claim a deferred payout (audit H17b).
 *
 * The contract's `withdraw()` reverts when there is nothing pending, and a
 * no-op would look like a successful claim — so this checks first and refuses
 * before spending the player's gas.
 */
export async function withdrawPending(): Promise<string> {
  await ensureCorrectChain();
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);

  const me = await signer.getAddress();
  const pending: bigint = await escrow.pendingWithdrawals(me);
  if (pending === 0n) {
    throw new Error(
      'Nothing to withdraw — the escrow does not owe you a deferred payout.',
    );
  }

  const tx = await escrow.withdraw({ gasPrice: await safeGasPrice() });
  await tx.wait();
  return tx.hash as string;
}

/** Anyone can trigger a timeout refund after MATCH_TIMEOUT. */
export async function refundTimeoutMatch(matchIdBytes32: string): Promise<string> {
  await ensureCorrectChain(); // H5
  const provider = requireInjected();
  const signer = await provider.getSigner();
  const escrow = new Contract(requireEscrowAddress(), PULSAR_ESCROW_ABI, signer);
  const tx = await escrow.refundTimeoutMatch(matchIdBytes32, { gasPrice: await safeGasPrice() });
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
