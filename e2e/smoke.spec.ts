/**
 * The first E2E test: the app boots against the real stack.
 *
 * This exists to prove the HARNESS, not the product — if it fails, every other
 * E2E failure is a harness failure and not a bug.
 */
import { test, expect } from '@playwright/test';
import { API_ORIGIN } from './helpers';

test.describe('the E2E harness', () => {
  test('the app boots and renders the landing surface', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#root')).not.toBeEmpty();
    // The header is the one element every route shares.
    await expect(page.getByRole('banner')).toBeVisible();
  });

  test('the API the app talks to is the real one', async ({ request }) => {
    const res = await request.get(`${API_ORIGIN}/api/health`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    // The point of the harness: production-like, not a dev bypass.
    expect(body.matchStore).toBe('firestore');
    expect(body.escrowConfigured).toBe(true);
    expect(body.rpc.reachable).toBe(true);
  });
});
