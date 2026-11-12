/**
 * i18n audit (2026-10-23) — the rules the audit established, pinned.
 *
 * The existing `translations.test.ts` proves the five dictionaries are complete
 * and consistent with each other. It cannot see the two things that actually
 * broke this UI:
 *
 *  1. COPY THAT NEVER REACHES A DICTIONARY. "Copied!", "Network", "Duels",
 *     "(est.)", "Loading…", "1-Tap Mobile Testing" and a full English sentence
 *     about pairing codes were rendered as literals in a product that offers
 *     five languages. Every one of them survived because no test looked at JSX.
 *  2. NUMBERS FORMATTED BY THE BROWSER INSTEAD OF THE PRODUCT. `toLocaleString()`
 *     with no argument reads the BROWSER locale, so the same amount rendered
 *     `1,234` for one user and `۱٬۲۳۴` for another — in a `font-mono` column
 *     beside a transaction hash. `src/lib/localeFormat.ts` is now the only
 *     formatter, and the policy is one numeral system for the whole product.
 *
 * These tests are RATCHETS: they fail on a NEW violation, and they carry an
 * explicit allowlist — with a reason — for the places where a physical value is
 * the correct choice.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { translations } from './translations';
import { formatClock, formatNumber, formatUsd } from '../lib/localeFormat';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

const FILES = walk(SRC).map((f) => ({
  path: path.relative(SRC, f).replace(/\\/g, '/'),
  lines: readFileSync(f, 'utf8').split('\n'),
}));

const LANGS = Object.keys(translations) as Array<keyof typeof translations>;

describe('the numeral policy holds in every language', () => {
  it('no dictionary value contains a non-Latin digit', () => {
    // Why this is a rule and not a preference: `{count}`, `{ms}` and every
    // amount come from the server as Latin digits. A Persian string with ۹۸ in
    // it puts two numeral systems on one screen — the exact defect
    // translations.test.ts already forbids *inside* one string. 35 strings had
    // to be converted when this rule was written; the message says what to do.
    const offenders: string[] = [];
    for (const lang of LANGS) {
      for (const [key, value] of Object.entries(translations[lang])) {
        if (/[\u06F0-\u06F9\u0660-\u0669]/.test(value)) {
          offenders.push(`${lang}.${key}: ${value}`);
        }
      }
    }
    expect(
      offenders,
      'Non-Latin digits found. The product prints Latin digits everywhere ' +
        '(see src/lib/localeFormat.ts); convert the digits, or change the policy ' +
        'in that file for EVERY number at once — not per string.\n' +
        offenders.join('\n')
    ).toEqual([]);
  });

  it('the Persian percent sign is still allowed (it is a symbol, not a digit)', () => {
    // A guard against over-correcting: `98٪` is correct Persian typography and
    // does not clash with a digit system. If this key ever loses its `٪`, the
    // test above is not the reason to keep it — but nothing else should strip it.
    expect(translations.fa.platformFee).toContain('٪');
  });
});

describe('numbers are formatted by the product, not by the browser', () => {
  it('no source file calls toLocaleString() with no argument', () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      file.lines.forEach((line, idx) => {
        if (/^\s*(\*|\/\/)/.test(line)) return; // comment, not code
        if (/\.toLocale(String|TimeString)\(\s*\)/.test(line)) {
          offenders.push(`${file.path}:${idx + 1}  ${line.trim()}`);
        }
      });
    }
    expect(
      offenders,
      'These read the BROWSER locale: the same number renders in different ' +
        'digits for different users. Use formatNumber/formatUsd/formatClock ' +
        'from src/lib/localeFormat.ts.\n' +
        offenders.join('\n')
    ).toEqual([]);
  });

  it('no toLocaleTimeString([]) with an options object either', () => {
    // `toLocaleTimeString([], {...})` is the same bug with extra steps: the
    // empty array means "browser default", and it also emits an AM/PM marker
    // that no dictionary can translate.
    const offenders: string[] = [];
    for (const file of FILES) {
      file.lines.forEach((line, idx) => {
        if (/^\s*(\*|\/\/)/.test(line)) return;
        if (/\.toLocaleTimeString\(\s*\[\s*\]/.test(line)) {
          offenders.push(`${file.path}:${idx + 1}  ${line.trim()}`);
        }
      });
    }
    expect(offenders, offenders.join('\n')).toEqual([]);
  });

  it('formatNumber is locale-proof and never emits non-Latin digits', () => {
    expect(formatNumber(1234.5)).toBe('1,234.5');
    expect(formatNumber(1_000_000)).toBe('1,000,000');
    expect(formatNumber(0.98)).toBe('0.98');
    expect(formatNumber(-42)).toBe('-42');
    expect(formatNumber(Number.NaN)).toBe('—');
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe('—');
    expect(formatUsd(0.98)).toBe('$0.98');
    expect(formatUsd(1234)).toBe('$1,234');
    for (const value of [0, 1, 12, 999999, 1234.5]) {
      expect(formatNumber(value)).not.toMatch(/[\u06F0-\u06F9\u0660-\u0669]/);
    }
  });

  it('formatClock is 24-hour and zero-padded, with no AM/PM', () => {
    const at = new Date(2026, 9, 23, 4, 5, 0).getTime();
    expect(formatClock(at)).toBe('04:05');
    expect(formatClock(at)).not.toMatch(/AM|PM|am|pm/);
    expect(formatClock('not a date')).toBe('—');
  });
});

describe('user-visible copy goes through the dictionary', () => {
  // Units, brands and protocol nouns that are correctly identical in every
  // language. Anything else written as a literal in JSX is an untranslated
  // string, whether or not it looks like one.
  const ALLOWED = new Set([
    'USDT',
    'XP',
    'EVM',
    'PULSAR',
    'Lv',
    'ms',
    'WalletConnect',
    'Settings',
    'iOS',
    'Android',
    'MetaMask',
    'Coinbase',
    'Trust',
    'Phantom',
  ]);

  it('no JSX text node is an untranslated English phrase', () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      if (!file.path.endsWith('.tsx')) continue;
      file.lines.forEach((line, idx) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
        for (const match of line.matchAll(/>([^<>{}]*[A-Za-z]{2,}[^<>{}]*)<\s*\//g)) {
          const text = match[1].trim();
          if (!text) continue;
          // Code that merely sits between angle brackets (`Promise<void>`, `=>`).
          // The regex already requires a closing tag (`</`), so a type argument
          // cannot match; this catches a JSX expression that happens to be text.
          if (/[=(){}[\]]/.test(text)) continue;
          if (!/[A-Za-z]{2,}/.test(text)) continue;
          const words = text.split(/\s+/).filter((w) => /[A-Za-z]/.test(w));
          const stripped = words
            .map((w) => w.replace(/[^A-Za-z]/g, ''))
            .filter((w) => w && !ALLOWED.has(w));
          if (stripped.length === 0) continue;
          // A single ALLOWED token with punctuation (`USDT`, `XP:`) is fine.
          offenders.push(`${file.path}:${idx + 1}  ${text}`);
        }
      });
    }
    expect(
      offenders,
      'These strings are rendered in every language. Move them into ' +
        'src/i18n/translations.ts and call t(); if a token is a brand, unit or ' +
        'protocol noun, add it to ALLOWED above with a reason.\n' +
        offenders.join('\n')
    ).toEqual([]);
  });

  it('the specific strings this audit fixed cannot come back', () => {
    // `i18n/translations.ts` is where these strings now LIVE (as the English
    // value). Scanning it would flag the fix as the bug.
    // Comments are not rendered: keep them out, or a comment that names the
    // string it removed reads as the string coming back.
    const source = FILES.filter((f) => f.path !== 'i18n/translations.ts')
      .map((f) => f.lines.filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n'))
      .join('\n');
    // A literal blacklist is weak on its own, but it documents exactly what was
    // wrong and survives the general scan being loosened later.
    for (const dead of [
      '1-Tap Mobile Testing',
      'Pairing code copied',
      '3-20 characters',
      '(est.)',
      '>Duels<',
      '>Copied<',
      '>Copy<',
      '>Network<',
      '>Token<',
      'Loading…',
    ]) {
      expect(source, `hardcoded copy returned: ${dead}`).not.toContain(dead);
    }
  });

  it('the wallet-connect sheet does not force a direction over translated copy', () => {
    const wallet = FILES.find((f) => f.path === 'components/ConnectWallet.tsx');
    expect(wallet).toBeDefined();
    const sheet = wallet!.lines.join('\n');
    // `direction: 'ltr'` is correct on numeric rows and address fragments; it is
    // wrong on a container that holds ~25 translated strings.
    const forced = sheet.match(/style=\{\{\s*direction:\s*'ltr'\s*\}\}/g) ?? [];
    // Two remain, both identity rows: the player tag + level, and the chain name
    // + chain id. Their content is Latin by construction (a player id, "Lv.7",
    // "Polygon Amoy", "80002"); a direction flip there would reorder glyphs
    // without changing a single word. Counted rather than allowlisted by line so
    // an addition anywhere in the file fails.
    expect(forced.length, 'a new forced-LTR block appeared in the wallet sheet').toBe(2);
  });
});

describe('RTL layout uses logical sides', () => {
  /**
   * Why this matters here specifically: `<html dir="rtl">` mirrors the flow but
   * NOT physical utilities. `text-left` on a Persian card forces English
   * alignment; `absolute left-3` puts a search icon on the trailing edge.
   *
   * The allowlist below is chrome that is deliberately LTR-locked (`dir="ltr"`
   * on its own element), where a physical side is the honest description.
   */
  const ALLOW: Record<string, string> = {
    'components/LanguageSelector.tsx':
      'the selector is LTR-locked on purpose: language names and flags read left-to-right in every locale',
  };

  it('no page or component aligns translated copy with a physical side', () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      if (!file.path.endsWith('.tsx')) continue;
      if (ALLOW[file.path]) continue;
      file.lines.forEach((line, idx) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
        if (/\btext-(left|right)\b/.test(line)) {
          offenders.push(`${file.path}:${idx + 1}  ${trimmed.slice(0, 120)}`);
        }
      });
    }
    expect(
      offenders,
      'Use text-start / text-end so the alignment follows the paragraph ' +
        'direction. If the element is LTR-locked on purpose, add it to ALLOW ' +
        'with the reason.\n' +
        offenders.join('\n')
    ).toEqual([]);
  });

  it('every RTL-locked allowlist entry states a reason', () => {
    for (const [file, reason] of Object.entries(ALLOW)) {
      expect(reason.length, `${file} needs a reason`).toBeGreaterThan(30);
    }
  });
});
