/**
 * Audit M-06 — a local timer must never announce a money outcome.
 *
 * `waitForOpponentDisclosure` polled for 120 seconds and then set
 * `outcome: 'void'`. The server's own decision window is SETTLE_GRACE (8
 * minutes), so the client declared a refund four times too early — and the
 * result screen renders anything that is not a win as "Defeat", with the
 * certificate recording a loss. A player who was about to win was told they lost.
 *
 * These tests pin the two halves of the fix: the wait covers the server's
 * horizon, and the exhausted wait is `pending` (unknown), not `void`.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SOURCE = readFileSync(resolve(__dirname, 'ReactionGamePage.tsx'), 'utf8');

describe('waiting for the server is not the same as losing (audit M-06)', () => {
  it('does not give up after 120 seconds', () => {
    const start = SOURCE.indexOf('const waitForOpponentDisclosure');
    const body = SOURCE.slice(start, start + 2000);
    expect(body).not.toMatch(/120_000/);
    expect(body).toMatch(/REFUND_OPENS_AFTER_MINUTES \* 60/);
  });

  it('reports an undecided duel as pending, never as void', () => {
    const start = SOURCE.indexOf('const waitForOpponentDisclosure');
    const body = SOURCE.slice(start, start + 4000);
    const pendingAt = body.indexOf("outcome: 'pending'");
    expect(pendingAt).toBeGreaterThan(-1);
    const after = body.slice(pendingAt);
    expect(after).not.toMatch(/outcome: 'void'/);
  });

  it('re-checks with the server before giving up', () => {
    const start = SOURCE.indexOf('const waitForOpponentDisclosure');
    const body = SOURCE.slice(start, start + 4000);
    expect(body).toMatch(/getMatch\(session, match\.matchId\)/);
  });

  it('renders pending and void with their own titles, not "defeat"', () => {
    expect(SOURCE).toMatch(/t\('matchPending'\)/);
    expect(SOURCE).toMatch(/t\('matchVoid'\)/);
    // The defeat title must still exist for real losses.
    expect(SOURCE).toMatch(/t\('matchDefeat'\)/);
  });

  it('does not offer a certificate for a duel with no result', () => {
    expect(SOURCE).toMatch(/matchResult\.outcome !== 'pending' && \(/);
  });

  it('translates the two new titles in every locale', () => {
    const translations = readFileSync(resolve(__dirname, '../i18n/translations.ts'), 'utf8');
    expect(translations.match(/matchPending:/g)?.length).toBe(5);
    expect(translations.match(/matchVoid:/g)?.length).toBe(5);
  });
});
