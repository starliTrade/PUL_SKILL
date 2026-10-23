/**
 * Audit M-14 — an unverified ranked profile must not render local numbers as stats.
 *
 * The store now records where the numbers came from (`progressionSource`), and
 * the profile is the screen that shows them. Rendering is asserted against the
 * source, the way the other screen-level pins in this repo are: jsdom + the
 * full store + the router is a lot of machinery for "does this branch exist",
 * and the branch is what has to be true in the shipped component.
 *
 * The interesting failure this prevents is silent: a ranked player whose
 * settlement failed — or whose ledger row is missing — sees "12 wins" that the
 * payout ledger has never heard of. "—" plus a reason is the honest answer.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const PROFILE = readFileSync(resolve(__dirname, 'ProfilePage.tsx'), 'utf-8');
const I18N = readFileSync(resolve(__dirname, '../i18n/translations.ts'), 'utf-8');

describe('profile renders unverified progression as unknown (audit M-14)', () => {
  it('derives the flag from the store provenance, not from a local guess', () => {
    expect(PROFILE).toContain("const progressionUnknown = stats.progressionSource === 'unknown';");
  });

  it('routes every performance figure through the unknown-aware helper', () => {
    expect(PROFILE).toContain('const verified = (value: React.ReactNode) =>');
    for (const figure of [
      'verified(stats.totalMatches)',
      'verified(`${stats.wins}W - ${stats.losses}L`)',
      'verified(`${winRate}%`)',
      'verified(stats.xp)',
      'verified(stats.level)',
    ]) {
      expect(PROFILE).toContain(figure);
    }
    // The raw values must not be rendered anywhere the player reads a stat.
    expect(PROFILE).not.toContain('>{stats.totalMatches}<');
    expect(PROFILE).not.toContain('>{stats.xp}<');
    expect(PROFILE).not.toContain('>{stats.level}<');
  });

  it('explains WHY the number is missing and offers a re-check', () => {
    expect(PROFILE).toContain("t('progressionUnverified')");
    expect(PROFILE).toContain("t('progressionRetry')");
    expect(PROFILE).toContain('onClick={handleRecheckProgression}');
    expect(PROFILE).toContain('await refreshProgression();');
    // A notice, not an error dialog: the profile is still usable.
    expect(PROFILE).toContain('role="status"');
  });

  it('has the explanation in all five locales', () => {
    const keys = ['progressionUnverified', 'progressionRetry', 'progressionChecking'];
    for (const key of keys) {
      const occurrences = I18N.split(`    ${key}: '`).length - 1;
      expect(occurrences, `${key} missing from one of the 5 locales`).toBe(5);
    }
  });
});
