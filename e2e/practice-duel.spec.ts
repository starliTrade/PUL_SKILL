/**
 * Plan item 10.1 — the core game loop, end to end, against the real stack.
 *
 * Practice mode is the honest first target: it exercises the whole round
 * machine (verify → countdown → wait → target → score → result) without a
 * wallet, so a failure here is a product failure and not a wallet-mock
 * failure. The ranked flow is a separate spec.
 */
import { test, expect } from '@playwright/test';
import { clearEligibilityGate, playPracticeDuel } from './helpers';

test.describe('the practice duel loop', () => {
  test('plays a best-of-three from the lobby to the result screen', async ({ page }) => {
    await page.goto('/lobby');
    await clearEligibilityGate(page);

    await page.getByRole('button', { name: /Free Training/i }).click();

    // Enter the arena.
    const enter = page.getByRole('button', { name: /Enter|Start/i }).first();
    await expect(enter).toBeVisible({ timeout: 15_000 });
    await enter.click();

    await expect(page.getByTestId('pulsar-game-root')).toBeVisible({ timeout: 20_000 });
    await playPracticeDuel(page);

    // The duel reached a terminal screen.
    await expect(page.getByTestId('pulsar-result')).toBeVisible({ timeout: 30_000 });
  });
});
