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
});
