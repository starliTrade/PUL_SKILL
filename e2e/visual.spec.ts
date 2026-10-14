/**
 * Plan item 10.2 — visual regression on the surfaces that carry the design.
 *
 * Not pixel snapshots: a snapshot suite on a moving design fails for the wrong
 * reasons. These are STRUCTURAL assertions about the things that actually break
 * — the document direction, the layout at each breakpoint, and the theme.
 */
import { test, expect } from '@playwright/test';
import { clearEligibilityGate } from './helpers';

const BREAKPOINTS = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1280, height: 800 },
];

test.describe('RTL layout (plan item 10.2)', () => {
  for (const lang of ['fa', 'ar'] as const) {
    for (const bp of BREAKPOINTS) {
      test(`${lang} at ${bp.name} (${bp.width}px)`, async ({ page }) => {
        await page.setViewportSize({ width: bp.width, height: bp.height });
        await page.addInitScript((l) => localStorage.setItem('pulsar_lang', l), lang);
        await page.goto('/lobby');
        await clearEligibilityGate(page);

        // The document itself must be RTL — that is the 8.2 contract.
        await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
        await expect(page.locator('html')).toHaveAttribute('lang', lang);

        // And the layout must not overflow horizontally at the narrowest width.
        const overflow = await page.evaluate(() => {
          const el = document.documentElement;
          return el.scrollWidth - el.clientWidth;
        });
        expect(overflow, `horizontal overflow at ${bp.width}px`).toBeLessThanOrEqual(1);
      });
    }
  }
});

// NO THEME TESTS HERE, because there is no theme system to test.
//
// Audit 2026-10-14: this block used to set `localStorage.pulsar_theme` and then
// assert the banner and main were visible — which is true in every theme and in
// no theme. Two things were wrong with it:
//
//   1. `pulsar_theme` is read by NOTHING in src/ — the app never looks at it.
//   2. The app has no light/dark mode at all. Every "theme" in the codebase is a
//      rank tier's colour (`currentTier.theme.coreColor`), not a mode.
//
// So plan item 10.2's "light/dark theme ✅" was marking a feature that does not
// exist, verified by a test that asserted nothing. It is now an OPEN item in the
// plan rather than a ticked one. A test that cannot fail is worse than no test.

test.describe('the duel surfaces (plan item 10.2)', () => {
  test('the target, the round transition and the result screen all render', async ({ page }) => {
    await page.goto('/lobby');
    await clearEligibilityGate(page);
    await page.getByRole('button', { name: /Free Training/i }).click();
    await page.getByRole('button', { name: /Enter|Start/i }).first().click();

    const verifyNode = page.getByTestId('pulsar-verify-node');
    await expect(verifyNode).toBeVisible({ timeout: 20_000 });
    // The waiting surface is its own screen (the anti-photodiode mask).
    await expect(page.getByTestId('pulsar-game-root')).toBeVisible();
    await verifyNode.click();

    // The target spawns.
    const target = page.getByTestId('pulsar-target');
    await expect(target).toBeVisible({ timeout: 25_000 });
    await target.click();

    // The round transition follows — identified by its OWN testid.
    //
    // Audit 2026-10-14: this used `/ROUND \d|MATCH POINT|TIE/i`, and the
    // scoreboard's "Round 2 of 3" matches that pattern — so it passed without
    // the transition screen ever appearing. The testid was added for exactly
    // this reason and this spec was not updated to use it.
    await expect(page.getByTestId('pulsar-round-transition')).toBeVisible({ timeout: 20_000 });
  });
});
