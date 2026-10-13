/**
 * Phase 7 / M34 + M35 — hardcoded chain copy and a stale WalletConnect URI.
 *
 * **M34.** `ConnectWallet.tsx` prints "Polygon PoS", "Chain 137", "Polygon
 * Mainnet (Chain 137)", "USDT (Tether USD)" and a truncated token address as
 * LITERALS. The app supports a testnet (Amoy, chain 80002) and reads its real
 * values from `CHAIN`/`TOKENS` everywhere else — so on testnet the wallet panel
 * tells the user they are on mainnet while the transactions go to Amoy. That is
 * the single most dangerous thing a money UI can say.
 *
 * **M35.** The handoff flow reuses `wcUriRef.current || realWeb3Manager.lastWcUri`
 * — a URI from a PREVIOUS attempt. A WalletConnect URI is single-use and
 * short-lived; reusing one shows a QR the wallet will refuse, and the user
 * cannot tell a stale QR from a broken app.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), 'src/components/ConnectWallet.tsx'),
  'utf8'
);

describe('the wallet panel reads the chain from config (audit M34)', () => {
  it('does not hardcode the mainnet chain id', () => {
    // "Chain 137" / "Chain 80002" as literals.
    expect(SRC).not.toMatch(/Chain\s+137/);
    expect(SRC).not.toMatch(/Chain\s+80002/);
  });

  it('does not hardcode the network name', () => {
    expect(SRC).not.toMatch(/Polygon\s+Mainnet/);
    expect(SRC).not.toMatch(/Polygon\s+PoS/);
  });

  it('does not hardcode the token symbol or name', () => {
    expect(SRC).not.toMatch(/USDT\s*\(Tether/);
  });

  it('does not hardcode a truncated token address', () => {
    expect(SRC).not.toMatch(/0xc213/);
  });

  it('reads the chain and token from the config module', () => {
    expect(SRC).toMatch(/CHAIN/);
    expect(SRC).toMatch(/TOKENS/);
  });
});

describe('the WalletConnect handoff does not reuse a stale URI (audit M35)', () => {
  it('does not fall back to lastWcUri for a NEW handoff', () => {
    // `wcUriRef.current || realWeb3Manager.lastWcUri` reuses a spent URI.
    expect(SRC).not.toMatch(/wcUriRef\.current\s*\|\|\s*realWeb3Manager\.lastWcUri/);
  });

  it('clears the stored URI when a handoff is cancelled', () => {
    expect(SRC).toMatch(/lastWcUri\s*=\s*(null|'')/);
  });
});
