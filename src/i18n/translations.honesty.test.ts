/**
 * Audit C-02b / H-08 (2026-10-22) — the UI must not claim capabilities the code
 * does not have.
 *
 * The product shipped strings that said a tap performed a "biometric anti-bot
 * handshake", that it "synchronized the hardware clock", that a "105ms anti-bot
 * floor" was an anti-bot measure, and that the client ran "input physics
 * analysis". None of that exists: the tap starts matchmaking, the server
 * enforces a timing floor and decides the round, and no biometric signal is ever
 * collected.
 *
 * This test scans the VALUES (never the keys — internal names may keep their
 * legacy spelling) in every locale, so the claims cannot creep back in a
 * translation nobody reviewed.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(path.join(HERE, 'translations.ts'), 'utf8');

/** Every `key: 'value',` pair in the file, with its line number. */
const STRINGS = SOURCE.split('\n')
  .map((line, idx) => {
    const m = line.match(/^\s*([A-Za-z0-9_]+):\s*'((?:[^'\\]|\\.)*)'/);
    return m ? { key: m[1], value: m[2], line: idx + 1 } : null;
  })
  .filter((x): x is { key: string; value: string; line: number } => x !== null);

const FORBIDDEN: Array<{ pattern: RegExp; why: string }> = [
  { pattern: /anti-?bot/i, why: 'there is no bot detection — only a server-side timing floor' },
  { pattern: /zero-?bot/i, why: 'nothing verifies "zero bots"' },
  { pattern: /biometric|بیومتریک|بيومتري/i, why: 'no biometric signal is collected or processed' },
  { pattern: /hardware clock|کلاک سخت‌افزاری|ساعة الأجهزة|donanım saati|硬件时钟/i, why: 'the tap does not calibrate any clock' },
  { pattern: /kinematic|کینماتیک|kinematiği|动力学/i, why: 'no kinematic model is fitted' },
  { pattern: /input physics|فیزیک ورودی|فيزياء الإدخال|Girdi Fiziği|物理分析/i, why: 'no physics simulation runs on the input' },
  { pattern: /ضد ?ربات|ضدربات|反机器人/i, why: 'no anti-bot mechanism exists' },
];

describe('i18n honesty (C-02b)', () => {
  it('loads the translation table it is checking', () => {
    expect(STRINGS.length).toBeGreaterThan(1000);
  });

  it.each(FORBIDDEN)('never ships "$pattern" in any locale', ({ pattern, why }) => {
    const offenders = STRINGS.filter((s) => pattern.test(s.value)).map(
      (s) => `${s.key} (line ${s.line}): "${s.value}"`
    );
    expect(offenders, `a string claims ${why}`).toEqual([]);
  });

  it('still tells the player the timing floor is enforced by the server', () => {
    const sub = STRINGS.filter((s) => s.key === 'realStakingSub');
    expect(sub.length).toBeGreaterThanOrEqual(5);
    for (const s of sub) {
      // Each locale must mention 105ms — the one number that is real.
      // Persian/Arabic locales may render the digits in their own script.
      expect(s.value).toMatch(/105ms|۱۰۵ms|١٠٥ms/);
    }
  });
});
