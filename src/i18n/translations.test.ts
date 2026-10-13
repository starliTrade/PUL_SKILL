/**
 * Translation-set integrity (audit 2026-10-13).
 *
 * The phase-8 audit checked these by hand and found real defects; this pins
 * them so the next translation cannot reintroduce them.
 *
 * 1. Every key must exist in ALL five languages. A missing key falls back to
 *    English (or renders the raw key), which is invisible until a user sees it.
 * 2. A parameterised key must use the SAME placeholders in every language. A
 *    translation that renames `{stake}` renders the literal `{stake}`.
 * 3. Placeholders use `{name}`, never `${name}`. `${name}` is JS template
 *    syntax: `interpolate()` splits on `{name}`, which is a SUBSTRING of
 *    `${name}`, so a stray `$` survives — it renders plausibly by accident.
 * 4. No key may mix digit systems inside one string: `{current}` is a JS
 *    number and always renders Latin, so a literal `۳` beside it is wrong.
 */
import { describe, it, expect } from 'vitest';
import { translations } from './translations';

const LANGS = Object.keys(translations) as Array<keyof typeof translations>;
const REFERENCE = 'en' as const;

const placeholders = (value: string): string[] =>
  [...value.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((m) => m[1]).sort();

describe('translation sets are complete and consistent', () => {
  it('has the same keys in every language, except the documented legal gap', () => {
    // The 43 `legal*` keys (Terms of Service, Privacy Policy, Risk Disclosure)
    // exist ONLY in English. Translating legal text is a lawyer's job: a
    // mistranslated ToS is a liability, so the gap is disclosed in the UI
    // (`legalEnglishOnly`) rather than machine-translated. Everything ELSE must
    // be complete — a new missing key fails here.
    const DOCUMENTED_GAP = /^legal(?!EnglishOnly)/;

    const reference = Object.keys(translations[REFERENCE]).sort();
    const problems: string[] = [];
    for (const lang of LANGS) {
      if (lang === REFERENCE) continue;
      const keys = new Set(Object.keys(translations[lang]));
      const missing = reference.filter((k) => !keys.has(k) && !DOCUMENTED_GAP.test(k));
      if (missing.length) {
        problems.push(`${lang}: missing ${missing.length} keys (${missing.slice(0, 5).join(', ')}…)`);
      }
    }
    expect(problems, problems.join('\n')).toEqual([]);
  });

  it('the documented legal gap is exactly the legal* keys', () => {
    // If someone translates the legal text, this test tells them to drop the
    // exemption above rather than leaving a stale allowlist behind.
    const legalKeys = Object.keys(translations[REFERENCE]).filter((k) => /^legal(?!EnglishOnly)/.test(k));
    for (const lang of LANGS) {
      if (lang === REFERENCE) continue;
      const present = legalKeys.filter((k) => k in (translations[lang] as Record<string, string>));
      // 43 of the 49 legal keys are English-only. If a translation lands, this
      // count changes and the exemption above must be narrowed.
      expect(present.length, `${lang} has ${present.length} legal keys — update the exemption`).toBe(6);
    }
  });

  it('uses the same placeholders in every language', () => {
    const problems: string[] = [];
    for (const [key, reference] of Object.entries(translations[REFERENCE])) {
      const expected = placeholders(reference);
      if (expected.length === 0) continue;
      for (const lang of LANGS) {
        if (lang === REFERENCE) continue;
        const value = (translations[lang] as Record<string, string>)[key];
        if (value === undefined) continue; // covered by the test above
        const actual = placeholders(value);
        if (actual.join(',') !== expected.join(',')) {
          problems.push(`${lang}.${key}: expected {${expected.join('} {')}}, got {${actual.join('} {')}}`);
        }
      }
    }
    expect(problems, problems.join('\n')).toEqual([]);
  });

  it('never uses ${name} template syntax in a translation', () => {
    const problems: string[] = [];
    for (const lang of LANGS) {
      for (const [key, value] of Object.entries(translations[lang] as Record<string, string>)) {
        if (/\$\{/.test(value)) problems.push(`${lang}.${key}: ${value}`);
      }
    }
    expect(problems, problems.join('\n')).toEqual([]);
  });

  it('does not mix Persian/Arabic digits with a Latin placeholder', () => {
    // `{current}` and friends always render Latin digits, so a literal Eastern
    // Arabic-Indic digit in the same string produces `راند 1 از ۳`.
    const EASTERN = /[\u0660-\u0669\u06F0-\u06F9]/;
    const problems: string[] = [];
    for (const lang of LANGS) {
      for (const [key, value] of Object.entries(translations[lang] as Record<string, string>)) {
        if (EASTERN.test(value) && placeholders(value).length > 0) {
          problems.push(`${lang}.${key}: ${value}`);
        }
      }
    }
    expect(problems, problems.join('\n')).toEqual([]);
  });
});
