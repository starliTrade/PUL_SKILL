/**
 * Local-chain helpers for the E2E suite (plan item 10.1).
 *
 * The ranked flow needs a player who actually HOLDS the payment token: the
 * server's deposit gate reads the escrow on-chain before every round, so a
 * player with an empty wallet is refused before the first target appears. The
 * deployer can mint MockUSDT, and anvil holds its key unlocked.
 */
import { readFileSync, existsSync } from 'node:fs';

export interface LocalManifest {
  rpcUrl: string;
  chainId: number;
  token: string;
  escrow: string;
  treasury: string;
  oracle: string;
  deployer: { address: string; privateKey: string };
  players: Array<{ address: string; privateKey: string }>;
}

export function readManifest(): LocalManifest {
  const path = 'contracts/deployments/local.json';
  if (!existsSync(path)) {
    throw new Error(`no manifest at ${path} — run scripts/start_anvil.sh --bg`);
  }
  return JSON.parse(readFileSync(path, 'utf8')) as LocalManifest;
}

async function rpc<T>(method: string, params: unknown[]): Promise<T> {
  const manifest = readManifest();
  const res = await fetch(manifest.rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method, params }),
  });
  const body = (await res.json()) as { result?: T; error?: { message: string } };
  if (body.error) throw new Error(`${method}: ${body.error.message}`);
  return body.result as T;
}

/** `MockUSDT.faucet(address,uint256)` — 6 decimals, so 1 USDT is 1_000_000.
 *
 * NOTE: the function is `faucet`, not `mint`. Calling a non-existent selector
 * does not revert on this contract, so the first version of this helper sent a
 * transaction that "succeeded" and credited nothing.
 */
export async function mintTestUSDT(to: string, wholeUsdt: number): Promise<void> {
  const manifest = readManifest();
  const selector = '0x7b56c2b2'; // faucet(address,uint256)
  const paddedTo = to.toLowerCase().replace(/^0x/, '').padStart(64, '0');
  const amount = BigInt(Math.round(wholeUsdt * 1_000_000)).toString(16).padStart(64, '0');
  await rpc('eth_sendTransaction', [
    {
      from: manifest.deployer.address,
      to: manifest.token,
      data: `${selector}${paddedTo}${amount}`,
      gas: '0x100000',
    },
  ]);
}

/** The token balance of an address, in whole USDT. */
export async function usdtBalanceOf(address: string): Promise<number> {
  const manifest = readManifest();
  const selector = '0x70a08231'; // balanceOf(address)
  const padded = address.toLowerCase().replace(/^0x/, '').padStart(64, '0');
  const raw = await rpc<string>('eth_call', [
    { to: manifest.token, data: `${selector}${padded}` },
    'latest',
  ]);
  return Number(BigInt(raw)) / 1_000_000;
}
