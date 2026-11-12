/**
 * The audit document is a claim about this repository. These checks keep it from
 * becoming a story: the numbers it prints must match the dictionaries, and the
 * "fixed" rows must still be fixed.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { translations } from './translations';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const DOC = readFileSync(path.join(ROOT, 'docs/I18N-AUDIT.md'), 'utf8');
const LANGS = Object.keys(translations) as Array<keyof typeof translations>;

describe('the i18n audit document matches the code', () => {
  it('quotes the key counts that the dictionaries actually have', () => {
    const en = Object.keys(translations.en).length;
    const other = Object.keys(translations.fa).length;
    expect(DOC).toContain(`| \`en\` | **${en}** |`);
    for (const lang of LANGS.filter((l) => l !== 'en')) {
      expect(Object.keys(translations[lang]).length, `${lang} drifted`).toBe(other);
    }
    expect(DOC).toContain(`| 459 |`);
  });

  it('quotes the number of new keys it added', () => {
    // 502 - 460 = 42. If the dictionary grows again, the sentence that says what
    // this pass added stops being true and must be updated with it.
    const added = Object.keys(translations.en).length - 460;
    expect(DOC).toContain(`**Total: ${added} new keys × 5 languages`);
  });

  it('the direction locks it says were removed are actually gone', () => {
    const wallet = readFileSync(path.join(HERE, '../components/ConnectWallet.tsx'), 'utf8');
    // The sheet is a portal rendered outside the LTR-locked header; a
    // `direction: 'ltr'` there applies to translated copy. Two identity rows are
    // the documented remainder.
    const locks = wallet.match(/style=\{\{\s*direction:\s*'ltr'\s*\}\}/g) ?? [];
    expect(locks.length).toBe(2);
    expect(DOC).toContain('| the wallet sheet | **removed**');
  });

  it('it does not claim a browser was used', () => {
    // The one thing this environment could not do. If someone runs the suite in a
    // real browser, this line becomes wrong and should be rewritten with the
    // evidence, not deleted.
    expect(DOC).toContain('no browser\nwas available');
  });
});
