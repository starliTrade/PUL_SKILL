/**
 * Plan items 8.1 and 8.2 — the document itself.
 *
 * 8.1: `maximum-scale=1, user-scalable=no` blocks pinch-zoom. WCAG 1.4.4
 * (Resize Text) requires that text can be magnified; the directive is a
 * deliberate accessibility regression, and nothing in this app needs it.
 *
 * 8.2: `<html lang>` and `dir` must follow the SELECTED language, not stay
 * `en`/`ltr` while the UI renders Persian or Arabic.
 */
import { describe, it, expect, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { render, cleanup, act } from '@testing-library/react';
import React from 'react';

import { LanguageProvider, useLanguage } from '../i18n/LanguageContext';

const INDEX_HTML = fs.readFileSync(path.resolve(process.cwd(), 'index.html'), 'utf8');


/** The element's opening tag, from `<` to the `>` that closes it. */
function openingTag(src: string, start: number): string {
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    const ch = src[i];
    if (ch === '{' || ch === '(') depth++;
    else if (ch === '}' || ch === ')') depth--;
    else if (ch === '>' && depth === 0 && src[i - 1] !== '=') return src.slice(start, i + 1);
  }
  return src.slice(start, start + 600);
}

describe('the document (plan items 8.1, 8.2)', () => {
  afterEach(() => {
    cleanup();
    document.documentElement.removeAttribute('dir');
    document.documentElement.lang = 'en';
    localStorage.clear();
  });

  it('does not block pinch-zoom (WCAG 1.4.4)', () => {
    // Assert on the meta tag's CONTENT, not the whole file: the comment above it
    // explains what was removed and would otherwise match.
    const meta = INDEX_HTML.match(/<meta\s+name="viewport"\s+content="([^"]*)"/i);
    expect(meta, 'no viewport meta tag found').toBeTruthy();
    const content = meta![1];
    expect(content).not.toMatch(/user-scalable\s*=\s*no/i);
    expect(content).not.toMatch(/maximum-scale\s*=\s*1\b/i);
    expect(content).toMatch(/width=device-width/);
  });

  it('declares a default lang on <html>', () => {
    expect(INDEX_HTML).toMatch(/<html[^>]*\blang="[a-z]{2}"/i);
  });

  it('follows the selected language for lang AND dir', async () => {
    let api: ReturnType<typeof useLanguage> | null = null;
    const Probe: React.FC = () => {
      api = useLanguage();
      return null;
    };
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>
    );

    // Persian is RTL.
    await act(async () => {
      api!.setLanguage('fa');
      await Promise.resolve();
    });
    expect(document.documentElement.lang).toBe('fa');
    expect(document.documentElement.dir).toBe('rtl');

    // English is LTR again.
    await act(async () => {
      api!.setLanguage('en');
      await Promise.resolve();
    });
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('does not force LTR on a panel of translated text (plan item 8.10)', () => {
    // A container that renders t(...) output must not pin direction: in Persian
    // and Arabic the word order and punctuation would be wrong. Numeric/hex
    // fragments keep an explicit dir — that is where it belongs.
    const files = [
      'src/pages/ReactionGamePage.tsx',
      'src/pages/ProfilePage.tsx',
      'src/pages/DashboardPage.tsx',
      'src/pages/LobbyPage.tsx',
    ];
    const offenders: string[] = [];
    for (const rel of files) {
      const src = fs.readFileSync(path.resolve(process.cwd(), rel), 'utf8');
      for (const m of src.matchAll(/dir="ltr"/g)) {
        const start = src.lastIndexOf('<', m.index);
        // The element's OWN opening tag only. Looking at the children produced
        // false positives (an LTR hex <span> followed by a translated label).
        const tag = openingTag(src, start);
        if (/\bt\('/.test(tag)) {
          offenders.push(`${rel}:${src.slice(0, m.index).split('\n').length}`);
        }
      }
    }
    expect(offenders, `translated panels pinned to LTR:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('honours prefers-reduced-motion (plan item 8.12)', () => {
    const css = fs.readFileSync(path.resolve(process.cwd(), 'src/index.css'), 'utf8');
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    const app = fs.readFileSync(path.resolve(process.cwd(), 'src/App.tsx'), 'utf8');
    expect(app).toMatch(/MotionConfig/);
    expect(app).toMatch(/reducedMotion="user"/);
  });

  it('has no hardcoded user-facing text left (plan item 8.9)', () => {
    // A brand name is the same in every language and stays a literal. Anything
    // else a user reads must come from translations.ts.
    const ALLOWED = new Set(['PULSAR PROTOCOL™', 'PULSAR PROTOCOL']);
    const files: string[] = [];
    for (const dir of ['src/components', 'src/pages']) {
      for (const name of fs.readdirSync(path.resolve(process.cwd(), dir))) {
        if (name.endsWith('.tsx') && !name.endsWith('.test.tsx')) files.push(`${dir}/${name}`);
      }
    }

    const offenders: string[] = [];
    for (const rel of files) {
      const src = fs.readFileSync(path.resolve(process.cwd(), rel), 'utf8');
      for (const m of src.matchAll(/>\s*([A-Z][A-Za-z][^<>{}\n]{6,80}?)\s*</g)) {
        const text = String(m[1]).trim();
        if (ALLOWED.has(text)) continue;
        offenders.push(`${rel}:${src.slice(0, m.start()).split('\n').length} "${text}"`);
      }
    }
    expect(offenders, `hardcoded user-facing text:\n${offenders.join('\n')}`).toEqual([]);
  });
});
