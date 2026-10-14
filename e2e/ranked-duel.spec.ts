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
 * STILL OPEN — and narrowed to one call. The creator's page sits on "Waiting
 * for a ranked opponent" while the other lands on the error shell with
 * `missing revert data (action="estimateGas")`.
 *
 * What has been RULED OUT, each by evidence rather than reasoning:
 *   - the CONTRACT flow: driving anvil directly with real transactions works
 *     (`approve` → allowance 1_000_000; `createDuel` → status Created;
 *     `joinDuel` → succeeds once the allowance exists);
 *   - the ADDRESSES the app uses: logged at the call site, `token` and
 *     `escrow` match the manifest exactly, chain 31337, stake 1;
 *   - the ROLE assignment: `youAreCreator` is `creator == me.address` on the
 *     server, and the two players queue in order.
 *
 *   - the ROLE assignment: tested against the live server, A (queued first)
 *     gets `youAreCreator: true`, B gets `youAreJoiner: true`, and a re-read
 *     agrees.
 *
 *   - the client's queue polling: it does re-poll with exponential backoff, and
 *     the server hands the creator the paired match on the very next poll
 *     (verified against the live API).
 *   - the gas price floor: chain 31337 falls back to 1 gwei, which anvil
 *     accepts.
 *
 * FIXED along the way — a real app bug, found by reading the FULL ethers error
 * rather than its message. `createDuel` is not idempotent: the contract reverts
 * with "Match already exists" when the duel is already on-chain, so ANY retry
 * of this flow re-created a funded duel and died on a revert — the player saw
 * "Could not reach the duel server" while their stake sat in the escrow. The
 * joiner already guarded for this; the creator now does too (it reads
 * `getDuelState` first and resumes instead of re-depositing).
 *
 * What is LEFT, and it is now measured: the FIRST round succeeds end to end
 * (`round/commit` 200, `round/target` 200 for one player), and the OTHER
 * player's requests come back `409 {"detail":"Match not found"}` carrying a
 * match id the server does not have. That id is the SAME across runs
 * (`de1b54c215…`), so it is deterministic for these two accounts — and because
 * `e2e/global-setup.ts` wipes the store between runs, the client is holding a
 * match id for a match that no longer exists. The next question is where the
 * client gets it: `recoverServerMatch` reads the persisted
 * `pulsar_active_ranked_match`, and a fresh browser context should have none.
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
      // the round counter advanced, and there is NO error shell.
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
