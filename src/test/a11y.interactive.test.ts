/**
 * Plan item 8.3 — every clickable element must be operable by keyboard.
 *
 * A source-level guard rather than a render test: the failure mode is a NEW
 * clickable `<div>`/`<span>` added later, which no existing render test would
 * notice. The rule is: an `onClick` on a non-interactive element must either be
 * a real `<button>`/`<a>`, or carry the ARIA button pattern
 * (`clickableDivProps`, which supplies role + tabIndex + Enter/Space).
 *
 * Backdrops and `stopPropagation` wrappers are excluded by name: they are not
 * controls, and closing a dialog is already reachable via Escape (item 8.4).
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const ROOT = process.cwd();
const INTERACTIVE = new Set([
  'button',
  'motion.button',
  'a',
  'input',
  'select',
  'textarea',
  'label',
  'summary',
]);

/**
 * Containers whose onClick is not a control affordance: a modal backdrop, or a
 * wrapper that only stops propagation. Closing a dialog is reachable via Escape
 * (item 8.4), so a backdrop needs no keyboard path of its own.
 */
const NON_CONTROL_MARKERS = [
  'stopPropagation',
  'onClose',
  'handleCloseModal',
  'setShowDepositModal(false)',
  'fixed inset-0',
];

function sourceFiles(): string[] {
  const dirs = ['src/components', 'src/pages'];
  const out: string[] = [];
  for (const dir of dirs) {
    for (const name of fs.readdirSync(path.join(ROOT, dir))) {
      if (name.endsWith('.tsx') && !name.endsWith('.test.tsx')) {
        out.push(path.join(dir, name));
      }
    }
  }
  return out;
}


/**
 * The element's opening tag, from `<` to the `>` that closes it.
 *
 * A naive `indexOf('>')` stops at the `>` of an arrow function's `=>`, which
 * truncated the tag and hid the markers this guard looks for.
 */
function openingTag(src: string, start: number): string {
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    const ch = src[i];
    if (ch === '{' || ch === '(') depth++;
    else if (ch === '}' || ch === ')') depth--;
    else if (ch === '>' && depth === 0 && src[i - 1] !== '=') return src.slice(start, i + 1);
  }
  return src.slice(start, start + 2000);
}

describe('clickable elements are keyboard-operable (plan item 8.3)', () => {
  it('no non-interactive element has a bare onClick', () => {
    const offenders: string[] = [];

    for (const rel of sourceFiles()) {
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      for (const match of src.matchAll(/onClick=/g)) {
        const start = src.lastIndexOf('<', match.index);
        if (start === -1) continue;
        const tag = /^<([A-Za-z][A-Za-z0-9.]*)/.exec(src.slice(start));
        if (!tag) continue;
        const name = tag[1];
        if (INTERACTIVE.has(name.toLowerCase())) continue;
        if (name[0] === name[0].toUpperCase()) continue; // a component owns its markup

        const openTag = openingTag(src, start);
        if (openTag.includes('clickableDivProps')) continue;
        if (openTag.includes('role="button"')) continue;
        if (NON_CONTROL_MARKERS.some((m) => openTag.includes(m))) continue;

        const line = src.slice(0, match.index).split('\n').length;
        offenders.push(`${rel}:${line} <${name}>`);
      }
    }

    expect(offenders, `these need a <button> or clickableDivProps():\n${offenders.join('\n')}`).toEqual([]);
  });

  it('the game targets are real buttons (plan item 8.11)', () => {
    const src = fs.readFileSync(path.join(ROOT, 'src/pages/ReactionGamePage.tsx'), 'utf8');
    // The verify node and the round target must be <button>s, so Enter/Space
    // activate them natively.
    for (const testId of ['pulsar-verify-node', 'pulsar-target']) {
      const idx = src.indexOf(`data-testid="${testId}"`);
      if (idx === -1) continue;
      const before = src.slice(Math.max(0, idx - 400), idx);
      expect(before, `${testId} is not a <button>`).toMatch(/<motion\.button|<button/);
    }
  });
});
