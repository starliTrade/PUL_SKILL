/**
 * Shared helpers for the E2E suite (plan item 10.1).
 */
import { type Page, expect } from '@playwright/test';

/** The eligibility gate is a first-visit dialog; every flow has to clear it. */
export async function clearEligibilityGate(page: Page): Promise<void> {
  const confirm = page.getByRole('button', { name: /Confirm & continue/i });
  if (await confirm.isVisible().catch(() => false)) {
    // The gate needs both declarations before its accept button enables.
    await page.getByRole('button', { name: /18 years/i }).click();
    await page.getByRole('button', { name: /not on the restricted/i }).click();
    await confirm.click();
  }
}

/** Play one round: wait for the target and hit it. */
export async function playOneRound(page: Page): Promise<void> {
  const target = page.getByTestId('pulsar-target');
  await expect(target).toBeVisible({ timeout: 20_000 });
  await target.click();
}

/** Drive the whole practice duel: verify node, then three rounds. */
export async function playPracticeDuel(page: Page): Promise<void> {
  const verifyNode = page.getByTestId('pulsar-verify-node');
  await expect(verifyNode).toBeVisible({ timeout: 20_000 });
  await verifyNode.click();

  for (let round = 0; round < 3; round += 1) {
    const target = page.getByTestId('pulsar-target');
    const result = page.getByTestId('pulsar-result');
    // Either the next target appears or the match ended (2-0).
    await expect(target.or(result)).toBeVisible({ timeout: 25_000 });
    if (await result.isVisible().catch(() => false)) return;
    await target.click();
    await page.waitForTimeout(300);
  }
}

/**
 * The API origin the specs talk to (audit L-04).
 *
 * `playwright.config.ts` already honours `PULSAR_E2E_API_PORT`, but three specs
 * hard-coded 8000 — so setting the port moved the server and left the tests
 * knocking on a closed door (measured: `ECONNREFUSED 127.0.0.1:8000` while the
 * stack was healthy on another port). One place now decides.
 */
export const API_ORIGIN = `http://127.0.0.1:${process.env.PULSAR_E2E_API_PORT ?? '8000'}`;
