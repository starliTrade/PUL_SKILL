/**
 * Plan item 10.1 — the ranked (real-stake) flow.
 *
 * Two players, two browser contexts, two anvil accounts, real MockUSDT, the
 * real escrow, and the server's deposit gate active the whole way.
 *
 * WHAT THIS COVERS: everything up to and including the pair. Both players
 * connect through an injected EIP-1193 provider, both enter the $1 tier, the
 * server pairs them, and both land in a real staked duel with the escrow
 * configured and the deposit gate armed.
 *
 * The blocker this spec used to document is FIXED: the mock wallet was passing
 * the SIWE message to anvil unencoded, and `personal_sign` takes it as HEX
 * (MetaMask encodes internally; a raw node does not). The app surfaced that
 * wallet error as "Could not reach the duel server", which is why it looked
 * like a server problem. See e2e/wallet.ts.
 */
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { clearEligibilityGate } from './helpers';
import { installMockWallet, ANVIL_ACCOUNTS } from './wallet';
import { mintTestUSDT, usdtBalanceOf } from './chain';

async function connectPlayer(context: BrowserContext, accountIndex: number): Promise<Page> {
  const page = await context.newPage();
  await installMockWallet(page, { accountIndex });
  await page.goto('/lobby');
  await clearEligibilityGate(page);
  await page.getByRole('button', { name: /Connect Wallet/i }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: /MetaMask/i }).first().click();
  // The connected chip replaces the Connect button.
  await expect(page.getByRole('button', { name: /Connect Wallet/i })).toHaveCount(0, {
    timeout: 20_000,
  });
  return page;
}

test.describe('the ranked duel', () => {
  // Desktop only: the mobile path routes through WalletConnect (a real relay),
  // so an injected provider is not what it uses. Driving the mobile ranked flow
  // needs a WalletConnect relay, which is a separate piece of infrastructure.
  test.skip(({ isMobile }) => !!isMobile, 'the mobile ranked path uses WalletConnect');

  test('two funded players pair into a real staked duel', async ({ browser }) => {
    // Fund both players with the token the escrow takes.
    for (const account of ANVIL_ACCOUNTS.slice(0, 2)) {
      await mintTestUSDT(account.address, 10);
    }
    expect(
      await usdtBalanceOf(ANVIL_ACCOUNTS[0].address),
      'the faucet helper must actually credit the player'
    ).toBeGreaterThanOrEqual(10);

    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    try {
      const pageA = await connectPlayer(ctxA, 0);
      const pageB = await connectPlayer(ctxB, 1);

      // Real-money mode must be AVAILABLE: it needs escrow + treasury + oracle
      // configured, and the lobby says so plainly when any is missing.
      await expect(pageA.getByText(/Real-Money Mode Unavailable/i)).toHaveCount(0);
      // The chain is the local one, not a public Amoy RPC.
      await expect(pageA.getByText(/Local Anvil/i).first()).toBeVisible();

      // Both enter the $1 tier. The first waits; the second pairs with them.
      await pageA.getByRole('button', { name: /Enter/i }).first().click();
      await pageA.waitForTimeout(2500);
      await pageB.getByRole('button', { name: /Enter/i }).first().click();

      // Both land on the duel screen.
      await expect(pageA.getByTestId('pulsar-game-root')).toBeVisible({ timeout: 40_000 });
      await expect(pageB.getByTestId('pulsar-game-root')).toBeVisible({ timeout: 40_000 });

      // TAPPING THE VERIFY NODE IS WHAT STARTS THE SERVER FLOW (SIWE → queue →
      // deposit). Without it the page sits in the local-bot path and every
      // assertion below would pass against a PRACTICE duel — which is exactly
      // the false green this spec shipped with.
      await pageA.getByTestId('pulsar-verify-node').click();
      await pageB.getByTestId('pulsar-verify-node').click();

      // The server flow must actually run: a real match, not the local bot.
      await expect(pageA.getByText(/Ranked · Server verified/i).first()).toBeVisible({
        timeout: 40_000,
      });

      // The round loop is NOT asserted here yet: the server refuses the first
      // commit with 409 because the app has not locked the stakes in the
      // escrow. The deposit gate is doing its job (fail-closed); what is
      // missing is the app's on-chain deposit step (approve → createDuel /
      // joinDuel) before the round flow starts. That is the next thing to fix,
      // and asserting the loop before it works would only hide it.
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });
});
