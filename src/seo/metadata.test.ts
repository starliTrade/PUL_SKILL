/**
 * Audit M-20 — share metadata and installability, asserted instead of assumed.
 *
 * The finding: `index.html` shipped `og:title`/`og:description` only — no image,
 * no url, `twitter:card: summary` — and the manifest advertised only SVG icons.
 * A link to the product rendered as a text row, and some launchers refused the
 * icon format. Nothing in the repository could fail if that regressed, because
 * metadata is invisible to every other test.
 *
 * These assertions are deliberately about the FILES THAT SHIP (index.html, the
 * manifest, the PNGs on disk), not about a React component: the crawler reads
 * the HTML, and it never runs the app.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { applySiteUrl, normalizeSiteUrl, seoMetaPlugin, SITE_URL_TOKEN } from '../../vite-plugin-seo';

const ROOT = resolve(__dirname, '../..');
const html = readFileSync(resolve(ROOT, 'index.html'), 'utf-8');
const manifest = JSON.parse(readFileSync(resolve(ROOT, 'public/manifest.webmanifest'), 'utf-8'));

/** Width/height from a PNG's IHDR chunk — no image library needed. */
function pngSize(path: string): { width: number; height: number } {
  const buf = readFileSync(path);
  expect(buf.subarray(1, 4).toString('ascii'), `${path} is not a PNG`).toBe('PNG');
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

const meta = (selector: string): string | undefined => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp(`<meta ${escaped} content="([^"]*)"`));
  return match?.[1];
};

describe('share metadata (audit M-20)', () => {
  it('declares a large-image card with a real image', () => {
    expect(meta('name="twitter:card"')).toBe('summary_large_image');
    expect(meta('property="og:image"')).toContain('/og-image.png');
    expect(meta('name="twitter:image"')).toContain('/og-image.png');
  });

  it('the image it points at exists and has the declared dimensions', () => {
    const size = pngSize(resolve(ROOT, 'public/og-image.png'));
    expect(String(size.width)).toBe(meta('property="og:image:width"'));
    expect(String(size.height)).toBe(meta('property="og:image:height"'));
    // Open Graph recommends 1200x630; smaller images are letter-boxed or dropped.
    expect(size.width).toBe(1200);
    expect(size.height).toBe(630);
  });

  it('gives crawlers a type, an alt text and a site url', () => {
    expect(meta('property="og:type"')).toBe('website');
    expect(meta('property="og:site_name"')).toBe('PULSAR');
    expect(meta('property="og:url"')).toBe(`${SITE_URL_TOKEN}/`);
    expect(meta('property="og:image:alt"')?.length).toBeGreaterThan(10);
    expect(meta('name="twitter:image:alt"')?.length).toBeGreaterThan(10);
  });

  it('does not promise anything the app cannot back up', () => {
    // The description is what a stranger reads before clicking. It must match
    // the contract (98% to the winner) and not imply a guarantee of profit.
    for (const value of [meta('property="og:description"'), meta('name="twitter:description"')]) {
      expect(value).toContain('98%');
      expect(value?.toLowerCase()).not.toContain('guaranteed');
      expect(value?.toLowerCase()).not.toContain('profit');
    }
  });

  it('ships a fallback for a visitor without JavaScript', () => {
    expect(html).toContain('<noscript>');
    expect(html).toContain('PULSAR needs JavaScript');
  });

  it('references an apple touch icon that exists at 180x180', () => {
    expect(html).toContain('rel="apple-touch-icon"');
    const size = pngSize(resolve(ROOT, 'public/apple-touch-icon.png'));
    expect(size).toEqual({ width: 180, height: 180 });
  });
});

describe('installability (audit M-20)', () => {
  it('offers a raster icon at the sizes launchers require', () => {
    const anyIcons = manifest.icons.filter((i: { purpose?: string }) => (i.purpose ?? 'any') === 'any');
    const sizes = anyIcons.map((i: { sizes: string }) => i.sizes);
    expect(sizes).toContain('192x192');
    expect(sizes).toContain('512x512');
    for (const icon of anyIcons.filter((i: { type: string }) => i.type === 'image/png')) {
      const path = resolve(ROOT, 'public', String(icon.src).replace(/^\//, ''));
      expect(existsSync(path), `${icon.src} is referenced but missing`).toBe(true);
      expect(pngSize(path)).toEqual({
        width: Number(String(icon.sizes).split('x')[0]),
        height: Number(String(icon.sizes).split('x')[1]),
      });
    }
  });

  it('offers a maskable icon so Android does not crop the logo', () => {
    const maskable = manifest.icons.filter((i: { purpose?: string }) => i.purpose === 'maskable');
    expect(maskable.length).toBeGreaterThan(0);
    for (const icon of maskable) {
      expect(existsSync(resolve(ROOT, 'public', String(icon.src).replace(/^\//, '')))).toBe(true);
    }
  });

  it('is installable: id, scope, start_url, display and colours', () => {
    expect(manifest.id).toBeTruthy();
    expect(manifest.scope).toBe('/');
    expect(manifest.start_url).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.background_color).toMatch(/^#[0-9a-f]{6}$/i);
    expect(manifest.theme_color).toMatch(/^#[0-9a-f]{6}$/i);
    // The theme colour in the HTML must be the manifest's, or the status bar
    // flashes a different colour when the PWA launches.
    expect(meta('name="theme-color"')).toBe(manifest.theme_color);
  });
});

describe('the __SITE_URL__ substitution (build-time)', () => {
  it('normalises a trailing slash away', () => {
    expect(normalizeSiteUrl('https://app.example.com/')).toBe('https://app.example.com');
    expect(normalizeSiteUrl('  https://app.example.com//  ')).toBe('https://app.example.com');
    expect(normalizeSiteUrl(undefined)).toBe('');
  });

  it('produces one slash between the origin and the path', () => {
    const out = applySiteUrl('<meta property="og:image" content="__SITE_URL__/og-image.png">', 'https://a.io/');
    expect(out).toContain('content="https://a.io/og-image.png"');
  });

  it('degrades to a relative URL rather than a broken absolute one', () => {
    const out = applySiteUrl('<meta property="og:url" content="__SITE_URL__/">', '');
    expect(out).toContain('content="/"');
    expect(out).not.toContain(SITE_URL_TOKEN);
  });

  it('warns on a production build with no origin configured', () => {
    const warnings: string[] = [];
    const plugin = seoMetaPlugin({ siteUrl: '', warn: (m) => warnings.push(m) });
    // `configResolved` receives the Vite config; only `command` matters here.
    (plugin.configResolved as (c: unknown) => void)({ command: 'build', env: {} });
    (plugin.transformIndexHtml as (h: string) => string)(html);
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toContain('VITE_SITE_URL');
  });

  it('stays quiet when the origin IS configured', () => {
    const warnings: string[] = [];
    const plugin = seoMetaPlugin({ siteUrl: 'https://app.example.com', warn: (m) => warnings.push(m) });
    (plugin.configResolved as (c: unknown) => void)({ command: 'build', env: {} });
    const out = (plugin.transformIndexHtml as (h: string) => string)(html) as string;
    expect(warnings).toEqual([]);
    expect(out).toContain('content="https://app.example.com/og-image.png"');
    expect(out).not.toContain(SITE_URL_TOKEN);
  });
});
