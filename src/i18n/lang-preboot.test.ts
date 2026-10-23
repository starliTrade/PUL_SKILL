/**
 * Audit L-14 — the document direction must be right on the FIRST paint.
 *
 * `<html lang="en">` was static and `dir` was set only by `LanguageProvider`,
 * i.e. after React mounts. A Persian or Arabic player therefore got the whole
 * app laid out LTR and then a document-wide flip to RTL — a reflow of every
 * element, on a screen whose job is to measure reaction times.
 *
 * The fix is an inline pre-boot script in `index.html`. These tests EXECUTE the
 * shipped script (not a copy of it) against a fake document, and pin the two
 * things that would silently break it: the storage key must match the
 * provider's, and the script must stay dependency-free (it runs before any
 * module, and a syntax error there is a blank page).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');
const html = readFileSync(resolve(ROOT, 'index.html'), 'utf-8');

function prebootSource(): string {
  const match = html.match(/<script id="pulsar-lang-preboot">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('the pre-boot language script is missing from index.html');
  return match[1];
}

interface Fake {
  doc: {
    documentElement: { lang: string; dir: string; classList: { add(c: string): void; remove(c: string): void } };
  };
}

function runPreboot(opts: {
  saved?: string | null;
  languages?: string[];
  storageThrows?: boolean;
}): Fake {
  const classes = new Set<string>();

  const doc = {
    documentElement: {
      lang: 'en',
      dir: 'ltr',
      classList: {
        add: (c: string) => classes.add(c),
        remove: (c: string) => classes.delete(c),
      },
    },
  };

  const win = {
    localStorage: {
      getItem: (key: string) => {
        if (opts.storageThrows) throw new Error('denied');
        expect(key).toBe('pulsar_lang');
        return opts.saved ?? null;
      },
    },
    navigator: { languages: opts.languages ?? [], language: (opts.languages ?? ['en'])[0] },
    document: doc,
  };

  const fn = new Function('window', 'document', 'navigator', 'localStorage', prebootSource());
  fn(win, doc, win.navigator, win.localStorage);
  (doc.documentElement as unknown as { __classes: Set<string> }).__classes = classes;
  return { doc };
}

function rtlApplied(fake: Fake): boolean {
  const cl = (fake.doc.documentElement as unknown as { __classes: Set<string> }).__classes;
  return cl.has('rtl');
}

describe('language is applied before first paint (audit L-14)', () => {
  it('ships the script, and it runs before the module entry', () => {
    expect(html).toContain('<script id="pulsar-lang-preboot">');
    expect(html.indexOf('pulsar-lang-preboot')).toBeLessThan(html.indexOf('/src/main.tsx'));
  });

  it('defaults to English/LTR with no saved language and an unknown locale', () => {
    const fake = runPreboot({ saved: null, languages: ['de-DE', 'de'] });
    expect(fake.doc.documentElement.lang).toBe('en');
    expect(fake.doc.documentElement.dir).toBe('ltr');
    expect(rtlApplied(fake)).toBe(false);
  });

  it('applies RTL for a saved Persian choice', () => {
    const fake = runPreboot({ saved: 'fa', languages: ['en-US'] });
    expect(fake.doc.documentElement.lang).toBe('fa');
    expect(fake.doc.documentElement.dir).toBe('rtl');
    expect(rtlApplied(fake)).toBe(true);
  });

  it('applies RTL for a saved Arabic choice', () => {
    const fake = runPreboot({ saved: 'ar', languages: ['en-US'] });
    expect(fake.doc.documentElement.dir).toBe('rtl');
  });

  it('falls back to the browser locale when nothing is saved', () => {
    const fake = runPreboot({ saved: null, languages: ['fa-IR', 'fa'] });
    expect(fake.doc.documentElement.lang).toBe('fa');
    expect(fake.doc.documentElement.dir).toBe('rtl');
  });

  it('ignores a saved value that is not a supported language', () => {
    const fake = runPreboot({ saved: 'klingon', languages: ['en-GB'] });
    expect(fake.doc.documentElement.lang).toBe('en');
    expect(fake.doc.documentElement.dir).toBe('ltr');
  });

  it('survives localStorage throwing (private mode / blocked storage)', () => {
    const fake = runPreboot({ saved: null, languages: ['ar-EG'], storageThrows: true });
    expect(fake.doc.documentElement.lang).toBe('ar');
    expect(fake.doc.documentElement.dir).toBe('rtl');
  });

  it('clears a stale RTL class when the language is LTR', () => {
    const fake = runPreboot({ saved: 'en', languages: ['en'] });
    // The script must call remove('rtl'), not merely skip the add.
    expect(rtlApplied(fake)).toBe(false);
    expect(prebootSource()).toContain("else html.classList.remove('rtl')");
  });

  it('reads the SAME storage key LanguageProvider writes', () => {
    const provider = readFileSync(resolve(ROOT, 'src/i18n/LanguageContext.tsx'), 'utf-8');
    expect(provider).toContain("const STORAGE_KEY = 'pulsar_lang';");
    expect(prebootSource()).toContain("localStorage.getItem('pulsar_lang')");
  });

  it('stays dependency-free and keeps the M-20 properties', () => {
    const src = prebootSource();
    expect(src).not.toMatch(/import\s|require\(|postMessage|fetch\(/);
    // It must never be the thing that throws before React can load.
    expect(src).toContain('catch (e)');
  });

  it('the static fallback keeps lang and dir for crawlers and no-JS', () => {
    expect(html).toContain('<html lang="en" dir="ltr" class="dark">');
  });
});
