/**
 * Audit 2026-10-13 — the money surfaces must not invent numbers.
 *
 * The project's rule R5 ("no fabricated data") has been applied to individual
 * findings (M32, H16) but never as a standing guard. These are the four
 * fabrications the audit found on surfaces a player reads as fact:
 *
 *  1. the header's "Network latency: Nms · Polygon Escrow Node" — a random
 *     number, refreshed every four seconds;
 *  2. the leaderboard's USDT earnings — a computed guess (`wins * 1.96`)
 *     because the reader looked for a field the server never writes;
 *  3. the leaderboard's reaction time — a hardcoded 185ms;
 *  4. the "LIVE ARENA FEED" — the player's own history, shown when the real
 *     feed was empty.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const read = (rel: string) => fs.readFileSync(path.resolve(process.cwd(), rel), 'utf8');

/**
 * The source with comments removed.
 *
 * The fixes below document what they removed (e.g. "a computed guess —
 * `wins * 1.96`"), so a naive grep matches the explanation. This strips line and
 * block comments so the assertions look at CODE.
 */
const code = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n');

describe('no fabricated measurements on money surfaces (audit 2026-10-13)', () => {
  it('the header does not invent a network latency', () => {
    const src = code('src/components/AppHeader.tsx');
    expect(src).not.toMatch(/Math\.random\(\)/);
    expect(src).not.toMatch(/Network latency/);
  });

  it('the leaderboard reader does not invent earnings or a reaction time', () => {
    const src = code('src/lib/realWeb3.ts');
    // The guess that stood in for real earnings.
    expect(src).not.toMatch(/\*\s*1\.96/);
    // The invented reaction time.
    expect(src).not.toMatch(/\|\|\s*185\b/);
    // A random address for a row that has none.
    expect(src).not.toMatch(/Math\.random\(\)\.toString\(16\)/);
    // ...and it reads the field the server actually writes.
    expect(src).toMatch(/val\.earnedUSDT/);
  });

  it('the dashboard does not invent a reaction time', () => {
    const src = code('src/pages/DashboardPage.tsx');
    expect(src).not.toMatch(/\|\|\s*180\b/);
  });

  it('the live feed is the live feed, not the player history', () => {
    const src = code('src/pages/LobbyPage.tsx');
    expect(src).not.toMatch(/liveCloudMatches\.length > 0 \? liveCloudMatches : history/);
  });

  it('the server writes the leaderboard fields the client reads', () => {
    const server = code('api/economy.py');
    expect(server).toMatch(/"earnedUSDT"/);
    expect(server).toMatch(/"bestReactionMs"/);
  });
});
