/**
 * A mock EIP-1193 wallet for the E2E suite (plan item 10.1).
 *
 * Not a stub: it proxies to the local anvil node, which holds the test accounts
 * unlocked and can really sign. So `personal_sign` produces a signature the
 * server actually verifies, and `eth_sendTransaction` really moves test funds —
 * which is what makes the ranked flow, the transaction-rejection path and the
 * network-switch path testable at all.
 *
 * The failure modes are the point: a wallet that cannot refuse is not a wallet.
 */
import { type Page } from '@playwright/test';

export interface MockWalletOptions {
  /** Which anvil account to expose. Defaults to the first. */
  accountIndex?: number;
  /** Reject every signature/transaction, like a user pressing "Cancel". */
  rejectTransactions?: boolean;
  /** Make every RPC call fail, like a wallet whose node is unreachable. */
  failRpc?: boolean;
  /** Report a different chain id, to drive the network-mismatch path. */
  chainId?: number;
  /** Report no accounts until `eth_requestAccounts` is called. */
  locked?: boolean;
}

export const ANVIL_ACCOUNTS = [
  { address: '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266', key: '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80' },
  { address: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8', key: '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d' },
  { address: '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC', key: '0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a' },
] as const;

/** Install the mock provider before the app boots. */
export async function installMockWallet(page: Page, options: MockWalletOptions = {}): Promise<void> {
  const {
    accountIndex = 0,
    rejectTransactions = false,
    failRpc = false,
    chainId = 31337,
    locked = false,
  } = options;

  await page.addInitScript(
    ({ accountIndex, rejectTransactions, failRpc, chainId, locked, accounts }) => {
      const ANVIL_RPC = 'http://127.0.0.1:8545';
      const account = accounts[accountIndex];
      let connected = !locked;

      const listeners: Record<string, Array<(...args: unknown[]) => void>> = {};
      const emit = (event: string, ...args: unknown[]) => {
        (listeners[event] ?? []).forEach((fn) => fn(...args));
      };

      const reject = () => {
        const err = new Error('User rejected the request.') as Error & { code: number };
        err.code = 4001;
        return err;
      };

      const provider = {
        isMetaMask: true,
        chainId: `0x${chainId.toString(16)}`,
        selectedAddress: locked ? null : account.address,
        request: async ({ method, params }: { method: string; params?: unknown[] }) => {
          if (failRpc) throw new Error('RPC endpoint unreachable');

          switch (method) {
            case 'eth_requestAccounts':
              connected = true;
              provider.selectedAddress = account.address;
              emit('accountsChanged', [account.address]);
              return [account.address];
            case 'eth_accounts':
              return connected ? [account.address] : [];
            case 'eth_chainId':
              return `0x${chainId.toString(16)}`;
            case 'net_version':
              return String(chainId);
            case 'wallet_switchEthereumChain':
              return null;
            case 'wallet_addEthereumChain':
              return null;
            case 'personal_sign':
            case 'eth_sign': {
              if (rejectTransactions) throw reject();
              // Forward to anvil, which holds the key and can really sign.
              const args = (params ?? []) as string[];
              // EIP-1193 does not fix the argument order: MetaMask takes
              // [message, address], some wallets take [address, message]. Pick
              // by shape rather than assuming.
              const msg = args.find((a) => typeof a === 'string' && !/^0x[0-9a-fA-F]{40}$/.test(a));
              const signer = args.find((a) => typeof a === 'string' && /^0x[0-9a-fA-F]{40}$/.test(a));
              // `personal_sign` takes the message as a HEX string. MetaMask
              // hex-encodes it internally; a raw RPC node (anvil) does not, and
              // answers `invalid value: string "…" expected a valid hex string`
              // for a plain message. Passing it through unchanged made the app
              // surface a WALLET error as "Could not reach the duel server".
              const hexMessage = msg.startsWith('0x') ? msg : `0x${toHex(msg)}`;
              const signed = await proxy('personal_sign', [hexMessage, signer ?? account.address]);
              if (typeof signed !== 'string' || !signed.startsWith('0x')) {
                throw new Error(
                  `the mock wallet did not get a signature back: ${String(signed).slice(0, 60)}`
                );
              }
              return signed;
            }
            case 'eth_sendTransaction':
              if (rejectTransactions) throw reject();
              return proxy('eth_sendTransaction', [
                { ...((params as Record<string, unknown>[])[0] ?? {}), from: account.address },
              ]);
            default:
              return proxy(method, params ?? []);
          }
        },
        on: (event: string, handler: (...args: unknown[]) => void) => {
          (listeners[event] ??= []).push(handler);
        },
        removeListener: (event: string, handler: (...args: unknown[]) => void) => {
          listeners[event] = (listeners[event] ?? []).filter((fn) => fn !== handler);
        },
        // ethers v6 (used by the app) probes these.
        enable: async () => [account.address],
        send: (method: string, params: unknown[]) => provider.request({ method, params }),
        sendAsync: (
          payload: { method: string; params?: unknown[] },
          cb: (err: unknown, res: unknown) => void
        ) => {
          provider
            .request(payload)
            .then((result) => cb(null, { id: 1, jsonrpc: '2.0', result }))
            .catch((err) => cb(err, null));
        },
      };

      function toHex(text: string): string {
        return Array.from(new TextEncoder().encode(text))
          .map((b) => b.toString(16).padStart(2, '0'))
          .join('');
      }

      async function proxy(method: string, params: unknown[]) {
        const res = await fetch(ANVIL_RPC, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method, params }),
        });
        const body = await res.json();
        if (body.error) throw new Error(body.error.message ?? 'rpc error');
        return body.result;
      }

      // EIP-6963 discovery. The app listens for `announceProvider` AND asks for
      // providers with `requestProvider`, so the wallet must answer BOTH:
      // announcing once at init-script time happens before the app's listener
      // exists, and the provider would never be discovered.
      const detail = {
        // The app matches a provider by NAME or RDNS against the wallet the
        // user clicked, so the mock must announce the identity the test clicks —
        // otherwise the click falls through to the WalletConnect path, which
        // needs a real relay.
        info: { uuid: 'e2e-mock', name: 'MetaMask', icon: '', rdns: 'io.metamask' },
        provider,
      };
      (window as unknown as Record<string, unknown>).ethereum = provider;
      const announce = () =>
        window.dispatchEvent(new CustomEvent('eip6963:announceProvider', { detail }));
      window.addEventListener('eip6963:requestProvider', announce);
      announce();
    },
    { accountIndex, rejectTransactions, failRpc, chainId, locked, accounts: ANVIL_ACCOUNTS }
  );
}
