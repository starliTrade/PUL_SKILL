/**
 * Phase 7 / M43 + M33 — the i18n interpolator and the escrow-config source.
 *
 * **M43.** `t()` interpolates with
 * `text.replace(new RegExp(`{${paramKey}}`, 'g'), String(paramVal))`. Two
 * problems, both reachable from ordinary data:
 *
 *   - the KEY is interpolated into a regex, so a key containing a metacharacter
 *     produces a malformed pattern or matches the wrong thing;
 *   - the VALUE is a replacement STRING, so `$&`, `$1`, `` $` `` in a player's
 *     own nickname are interpreted as replacement patterns. A player called
 *     `$&` corrupts every message that names them.
 *
 * **M33.** `escrowStatus()` in `escrowFlow.ts` re-derives "is the escrow
 * configured" from `ESCROW.address` and `isPaymentTokenConfigured()`, while
 * `chain.ts` has its own `isEscrowConfigured()`. Two functions answering the
 * same question drift, and the UI then shows a different answer depending on
 * which one a component happened to import.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../lib/firebase', () => ({ getDb: () => null }));

// --- M43 ----------------------------------------------------------------------
describe('i18n interpolation is literal (audit M43)', () => {
  it('a value containing $& is not treated as a replacement pattern', async () => {
    const { interpolate } = await import('./interpolate');

    const out = interpolate('Player {name} won', { name: '$&' });

    expect(out).toBe('Player $& won');
  });

  it('a value containing $1 is not treated as a backreference', async () => {
    const { interpolate } = await import('./interpolate');

    const out = interpolate('Player {name} won', { name: '$1' });

    expect(out).toBe('Player $1 won');
  });

  it('a value containing a backtick and $` is literal', async () => {
    const { interpolate } = await import('./interpolate');

    const out = interpolate('Player {name} won', { name: '$`' });

    expect(out).toBe('Player $` won');
  });

  it('a key containing a regex metacharacter does not break the pattern', async () => {
    const { interpolate } = await import('./interpolate');

    // `{a.b}` — the dot is a regex metacharacter.
    const out = interpolate('x {a.b} y', { 'a.b': 'VALUE' });

    expect(out).toBe('x VALUE y');
  });

  it('every occurrence is replaced', async () => {
    const { interpolate } = await import('./interpolate');

    expect(interpolate('{n} and {n}', { n: 'X' })).toBe('X and X');
  });

  it('a missing param leaves the placeholder alone', async () => {
    const { interpolate } = await import('./interpolate');

    expect(interpolate('{a} {b}', { a: '1' })).toBe('1 {b}');
  });

  it('numbers are stringified', async () => {
    const { interpolate } = await import('./interpolate');

    expect(interpolate('{n}ms', { n: 220 })).toBe('220ms');
  });
});

// --- M33 ----------------------------------------------------------------------
describe('one source of truth for the escrow config (audit M33)', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('escrowStatus agrees with isEscrowConfigured', async () => {
    const chain = await import('../lib/chain');
    const flow = await import('../lib/escrowFlow');

    // Whatever the environment, the two must not disagree.
    expect(flow.escrowStatus().configured).toBe(chain.isEscrowConfigured());
  });

  it('escrowStatus is derived from the chain module, not re-derived', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.resolve(process.cwd(), 'src/lib/escrowFlow.ts'),
      'utf8'
    );

    // The function must CALL the shared predicate rather than repeat its logic.
    expect(src).toMatch(/isEscrowConfigured\(\)/);
  });
});
