/**
 * Plan item 9.7 — the phase-9 EXIT GATE.
 *
 * "A CI test that rejects any `Math.random()` on a money surface."
 *
 * `Math.random()` is not banned: a reaction game NEEDS a random target position
 * (that is the anti-photodiode measure) and a starfield needs random stars. What
 * is banned is a random number presented to the player as a MEASUREMENT or a
 * MONEY value — the M32 class, which shipped in four places:
 *
 *   - a random leaderboard address and a random "earned USDT";
 *   - a fabricated 180ms/185ms reaction time when a match had none;
 *   - a random "Network latency: 14-22ms" in the header;
 *   - a random "{n}ms Global Sync" ping on the hero.
 *
 * The gate has two halves:
 *   1. every file that calls `Math.random()` must be on the allowlist below,
 *      with the reason it is legitimate — so a NEW file cannot quietly add one;
 *   2. no `Math.random()` expression may be assigned to a state/const whose name
 *      reads like a measurement or a money value.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const ROOT = process.cwd();

/**
 * Files allowed to use `Math.random()`, and why.
 *
 * Keep this list SHORT and the reasons specific. "It was already there" is not
 * a reason.
 */
const ALLOWED: Record<string, string> = {
  'src/lib/antiCheat.ts':
    'the target spawn position (the anti-photodiode measure), practice bot names, and the practice-mode opponent simulation',
  'src/components/HeroTextCosmicBackdrop.tsx': 'starfield rendering',
  'src/components/PulsarCosmicBackground.tsx': 'starfield rendering',
  'src/components/PulsarHeroVisualizer.tsx':
    'starfield rendering and the reflex test\'s random wait (a reaction test must not be predictable)',
  'src/pages/ReactionGamePage.tsx':
    'the calibration target position and the practice-mode target delay',
};

/** A name that reads like a measurement or money must never come from random. */
const FABRICATION_SHAPED = /(ping|latency|rtt|earn|prize|balance|payout|address|usdt|winnings)/i;

/**
 * The code lines only — a comment that MENTIONS `Math.random()` (this gate's own
 * documentation, and the notes explaining each removal) is not a call site.
 */
function codeLines(src: string): string[] {
  return src
    .split('\n')
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .filter((line) => !/\/\/.*Math\.random/.test(line));
}

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) out.push(rel);
    }
  };
  walk('src');
  return out;
}

describe('no fabricated data (plan item 9.7)', () => {
  it('every Math.random() call site is on the allowlist', () => {
    const offenders: string[] = [];
    for (const rel of sourceFiles()) {
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      const code = codeLines(src).join('\n');
      if (!code.includes('Math.random()')) continue;
      if (rel in ALLOWED) continue;
      const line = src.slice(0, src.indexOf('Math.random()')).split('\n').length;
      offenders.push(`${rel}:${line}`);
    }
    expect(
      offenders,
      `these use Math.random() without a documented reason:\n${offenders.join('\n')}\n` +
        'If it is legitimate, add the file to ALLOWED with a specific reason. ' +
        'If it feeds a number the player reads as a measurement or money, it is the M32 bug.'
    ).toEqual([]);
  });

  it('no measurement- or money-shaped value comes from Math.random()', () => {
    const offenders: string[] = [];
    for (const rel of sourceFiles()) {
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      for (const line of codeLines(src)) {
        if (!line.includes('Math.random()')) continue;
        // The assignment target, if any: `const x = …` / `setX(…)`.
        const decl = /(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=/.exec(line);
        const setter = /set([A-Za-z0-9_]+)\s*\(/.exec(line);
        const name = decl?.[1] ?? setter?.[1];
        if (name && FABRICATION_SHAPED.test(name)) {
          offenders.push(`${rel}: ${line.trim()}`);
        }
      }
    }
    expect(offenders, `a random value is feeding a measurement/money name:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('no bare measurement literal is rendered as a reading', () => {
    // The gate's blind spot: a HARDCODED number needs no randomness, so the
    // two checks above cannot see it — and a hardcoded number is the most
    // common shape of this bug ("180ms – 260ms" beside a pulsing dot, "+50 XP",
    // "185ms"). A bare measurement in a JSX text node must be a documented
    // constant, not a value that reads as a live measurement.
    //
    // `0 USDT` (practice stakes nothing) is the one legitimate case.
    const ALLOWED_LITERALS = new Set(['0 USDT']);
    const offenders: string[] = [];
    for (const rel of sourceFiles()) {
      if (!rel.endsWith('.tsx')) continue;
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      for (const m of src.matchAll(/>\s*([0-9]+(?:\.[0-9]+)?\s*(?:ms|%|USDT|XP))\s*</g)) {
        const value = m[1];
        if (ALLOWED_LITERALS.has(value)) continue;
        offenders.push(`${rel}:${src.slice(0, m.index).split('\n').length} "${value}"`);
      }
    }
    expect(
      offenders,
      `a hardcoded measurement is rendered as a reading:\n${offenders.join('\n')}\n` +
        'If it is a genuine constant, label it as one (a translated string that says what it is).'
    ).toEqual([]);
  });

  it('the allowlist has no stale entries', () => {
    // A file that no longer calls Math.random() should leave the list, so the
    // list keeps meaning "these are the places, today".
    const stale = Object.keys(ALLOWED).filter((rel) => {
      const full = path.join(ROOT, rel);
      if (!fs.existsSync(full)) return true;
      return !codeLines(fs.readFileSync(full, 'utf8')).join('\n').includes('Math.random()');
    });
    expect(stale, `remove these from ALLOWED: ${stale.join(', ')}`).toEqual([]);
  });
});
