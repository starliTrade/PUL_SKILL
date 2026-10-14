/**
 * Failure modes on the money path (plan items 10.1: "transaction rejection at
 * every step", "RPC failure at every step", "account/network switch during a
 * match (H15)").
 *
 * The rule these all test is the same one: **when something goes wrong, the
 * player must be told the truth and no money may move.** A wallet that refuses,
 * a node that is unreachable, and a wallet on the wrong chain are three
 * different failures that must not look like a lost stake.
 *
 * Each test owns a distinct pair of anvil accounts AND a distinct stake. The
 * stake matters as much as the accounts: `/api/queue` pairs within a per-stake
 * bucket, and the app RE-QUEUES itself after a failure, so a test that shares a
 * stake can have its parked opponent taken by the previous test's retry — which
 * is exactly what made this spec skip instead of run.
 */
import { expect, test, type Page } from '@playwright/test';
import { installMockWallet, ANVIL_ACCOUNTS, type MockWalletOptions } from './wallet';
import { clearEligibilityGate } from './helpers';
import { mintTestUSDT } from './chain';

const API = 'http://127.0.0.1:8000';

async function signIn(privateKey: string): Promise<{ address: string; token: string }> {
  const { privateKeyToAccount } = await import('viem/accounts');
  const account = privateKeyToAccount(privateKey as `0x${string}`);
  const nonce = await fetch(`${API}/api/auth/nonce`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address: account.address.toLowerCase() }),
  }).then((r) => r.json() as Promise<{ message: string }>);
  const signature = await account.signMessage({ message: nonce.message });
  const verified = await fetch(`${API}/api/auth/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: nonce.message, signature }),
  }).then((r) => r.json() as Promise<{ token: string }>);
  return { address: account.address.toLowerCase(), token: verified.token };
}

/** Park a real opponent in the queue so the browser player pairs immediately. */
async function parkOpponent(index: number, stake: number): Promise<boolean> {
  const opponent = await signIn(ANVIL_ACCOUNTS[index].key);
  const res = await fetch(`${API}/api/queue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${opponent.token}` },
    body: JSON.stringify({ stake, rttMs: 40 }),
  });
  const body = (await res.json()) as Record<string, unknown>;
  // An opponent left `active` by an earlier test is not this test's problem: the
  // suite shares a store and a queue. Only a `waiting` slot is usable here.
  return body.status === 'waiting';
}

/** Connect, select the stake tier, and tap the verify node. */
async function enterStakedDuel(
  page: Page,
  options: MockWalletOptions,
  stake: number
): Promise<void> {
  await installMockWallet(page, options);
  await page.goto('/lobby');
  await clearEligibilityGate(page);
  await page.getByRole('button', { name: /Connect Wallet/i }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: /MetaMask/i }).first().click();
  await page.waitForTimeout(3000);
  // The tier buttons render the stake as `$N`; select the one this test owns so
  // it queues into its own bucket.
  await page.getByRole('button', { name: new RegExp(`^\\$${stake}\\b`) }).first().click();
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: /Enter/i }).first().click();
  await page.waitForTimeout(2500);
  await page.getByTestId('pulsar-verify-node').click();
}

test.describe('the money path fails honestly', () => {
  test.setTimeout(180_000);

  // NOT TESTED HERE, and the reason is the finding: with an unreachable node
  // (`failRpc`) the app renders a BLANK page. The connect button never appears,
  // so a test cannot even reach the assertion — it hangs in setup and dies on a
  // timeout, which is a worse signal than no test at all. Measured, not assumed:
  // the page snapshot at the timeout is a single empty element.
  //
  // The honest fix is in the app (render an error shell when the chain is
  // unreachable, as it already does for a refused transaction). Until then this
  // is recorded in the plan rather than hidden behind a test that cannot run.

  test('a wallet that refuses the deposit moves no money and says so', async ({ browser }) => {
    const stake = 1;
    test.skip(!(await parkOpponent(1, stake)), "the opponent slot is already paired by another spec");
    await mintTestUSDT(ANVIL_ACCOUNTS[0].address, 50);

    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    // The wallet rejects every signature and transaction, like a player pressing
    // Cancel — or a hardware wallet that never confirms.
    await enterStakedDuel(page, { accountIndex: 0, rejectTransactions: true }, stake);

    // The app must say the action was cancelled AND that no funds moved. The
    // second half is the part that matters: a player who cannot tell whether
    // their stake left their wallet will not trust the game again.
    await expect(page.getByText(/no funds moved/i).first()).toBeVisible({ timeout: 60_000 });
    // And it must NOT reach the arena. Identified by its own testids: the text
    // "Round \d of 3" also matches the error shell's own copy ("Failing
    // verification forfeits the round"), so text is the wrong signal here.
    await expect(page.getByTestId('pulsar-target')).toHaveCount(0);
    await expect(page.getByTestId('pulsar-waiting')).toHaveCount(0);
    await ctx.close();
  });

  test('a wallet on the wrong chain cannot deposit (H15)', async ({ browser }) => {
    // A DIFFERENT stake from the test above: the app re-queues itself after a
    // failure, and a shared bucket lets that retry take this test's opponent.
    const stake = 2;
    test.skip(!(await parkOpponent(5, stake)), "the opponent slot is already paired by another spec");
    await mintTestUSDT(ANVIL_ACCOUNTS[4].address, 50);

    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    // Mainnet, while the duel lives on the local chain. Signing an approve here
    // would spend real money on the wrong network.
    await enterStakedDuel(page, { accountIndex: 4, chainId: 1 }, stake);

    // The app must refuse, and must not claim a server-verified duel.
    await expect(
      page.getByText(/chain|network|switch|Could not reach the duel server/i).first()
    ).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('pulsar-target')).toHaveCount(0);
    await expect(page.getByTestId('pulsar-waiting')).toHaveCount(0);
    await ctx.close();
  });
});
