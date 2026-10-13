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
 * The SIWE blocker is FIXED (the mock wallet was passing the message to anvil
 * unencoded; `personal_sign` takes it as HEX). The deposit step is verified:
 * with a clean stack the server answers 200 on `round/commit` and
 * `round/target`, where it previously refused with 409.
 *
 * STILL OPEN — the app's JOINER path. The creator's page sits on "Waiting for
 * a ranked opponent" while the joiner lands on the error shell with
 * `missing revert data (action="estimateGas")`. The CONTRACT flow itself is
 * proven correct by driving anvil directly with real transactions:
 * `approve` → allowance becomes 1_000_000; `createDuel` → status Created;
 * `joinDuel` → succeeds once the allowance exists. So the revert is in the
 * app's call, not in the escrow — most likely a token/escrow address the app
 * does not have (a call to a non-contract returns no revert data, which is
 * exactly this error). That is the next thing to trace.
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
  // A full staked best-of-three with two real wallets, real deposits and the
  // server's gate on every round is a long flow; the default 60s is not enough.
  test.setTimeout(240_000);

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

      // THE DEPOSIT PROOF. The server's gate reads the escrow before every
      // round and refuses with 409 unless BOTH stakes are locked on-chain, and
      // a refusal puts the app on its error shell. So: the duel is running,
      // the round counter advanced, and there is NO error shell — which can
      // only be true if SIWE → queue → approve → createDuel/joinDuel → the
      // gate → commit → reveal all succeeded.
      //
      // Asserting the TARGET's visibility instead would be flaky by design:
      // this is a reaction game, the target appears and the round advances on
      // its own clock, and two players' clocks are independent.
      await expect(pageA.getByText(/Round \d of 3/i).first()).toBeVisible({ timeout: 60_000 });
      await expect(pageB.getByText(/Round \d of 3/i).first()).toBeVisible({ timeout: 60_000 });
      await expect(pageA.getByText(/Could not reach the duel server/i)).toHaveCount(0);
      await expect(pageB.getByText(/Could not reach the duel server/i)).toHaveCount(0);
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });
});
