/**
 * Audit M-20 (leftover) — `index.html` must contain only OUR code.
 *
 * The file shipped a 690-line `BLINK_PICKER_RUNTIME_V2` block: a visual-editor
 * overlay from the site template the project started from. Nothing in PULSAR
 * used it, and it was not inert:
 *
 *   * `window.addEventListener('message', …)` with NO origin check, accepting
 *     `SET_ELEMENT_ATTRS` — which sets `el.style`, `el.className` and
 *     `el.textContent` on any element matched by a selector the CALLER supplies.
 *     A frame that can post to this window could relabel a stake, a payout or a
 *     button while the underlying handler stayed the same.
 *   * a `MutationObserver` on `documentElement` with `subtree: true`, plus
 *     per-frame rect measurement on scroll/resize — on a real-time game.
 *   * outbound `window.parent.postMessage(..., '*')` on every pick.
 *
 * This test asserts the CLASS, not the instance: no blink runtime, no
 * `postMessage` bridge, and no `message` listener in the shipped HTML. The
 * WalletConnect proposal-key purge is allowed to stay — it is ours, it touches
 * only `localStorage`, and the test below distinguishes the two.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');
const html = readFileSync(resolve(ROOT, 'index.html'), 'utf-8');
const lower = html.toLowerCase();

describe('index.html ships no foreign runtime (audit M-20 leftover)', () => {
  it('has no blink picker block', () => {
    expect(lower).not.toContain('blink');
  });

  it('has no postMessage bridge', () => {
    expect(lower).not.toContain('postmessage');
  });

  it('registers no message listener', () => {
    // The vector was `addEventListener('message')`, whichever spelling.
    expect(lower).not.toMatch(/addeventlistener\(\s*['"]message['"]/);
  });

  it('still has the block the reviewer was told never to remove', () => {
    // The comment said "DO NOT REMOVE" — it was attached to the foreign script,
    // so it went with it. Nothing else may claim that.
    expect(lower).not.toContain('do not remove');
  });

  it('keeps the WalletConnect proposal-key purge (our code, localStorage only)', () => {
    expect(html).toContain('wc@2:');
    expect(html).toContain('proposal');
    // …and it never becomes a message bridge itself.
    const script = html.slice(html.indexOf('Purge orphaned/stale WalletConnect'));
    const body = script.slice(0, script.indexOf('</script>'));
    expect(body.toLowerCase()).not.toContain('postmessage');
  });

  it('keeps the pinch-zoom decision documented', () => {
    // The viewport comment records WHY there is no `user-scalable=no`; it is the
    // kind of thing that gets silently re-added.
    expect(html).toContain('WCAG 1.4.4');
    expect(html).toContain('width=device-width, initial-scale=1.0');
  });

  it('has exactly one module entry, and it is ours', () => {
    const modules = [...html.matchAll(/<script[^>]*type=["']module["'][^>]*>/g)];
    expect(modules).toHaveLength(1);
    expect(html).toContain('<script type="module" src="/src/main.tsx"></script>');
  });
});

describe('the repo names no third-party code registry', () => {
  /**
   * `components.json` carried `"registries": {"@blink": "https://blink-ui-registry
   * .kai-96c.workers.dev/r/{name}.json"}` — the same template vendor. Nothing used
   * it (no `components/ui` directory, no shadcn dependency), but `npx shadcn add
   * @blink/button` would have fetched unvetted code from an unknown Cloudflare
   * Worker straight into a money app. An empty registry map is the honest state.
   */
  it('has an empty registry map', () => {
    const cfg = JSON.parse(readFileSync(resolve(ROOT, 'components.json'), 'utf-8'));
    expect(cfg.registries ?? {}).toEqual({});
  });
});
