import type { Plugin } from 'vite';

/**
 * Audit M-20 — the share metadata was static and had no real image.
 *
 * `index.html` shipped `og:title`/`og:description` and nothing else: no
 * `og:image`, no `og:url`, `twitter:card: summary` (a small card with no
 * picture). Every link to the product rendered as a bare text row, and the PWA
 * manifest advertised only SVGs, which some launchers refuse to rasterise.
 *
 * An absolute URL is required for `og:image` (crawlers do not resolve relative
 * paths), so the origin cannot be known until deploy time. `index.html` carries
 * `__SITE_URL__` tokens and this plugin fills them from `VITE_SITE_URL`.
 *
 * The failure this must NOT have is a silent one: a production build with no
 * `VITE_SITE_URL` would ship `content="/og-image.png"`, which some crawlers
 * resolve and others drop. So the build WARNS, and a missing value degrades to
 * a relative path instead of producing a broken absolute one.
 */
export const SITE_URL_TOKEN = '__SITE_URL__';

export function normalizeSiteUrl(raw: string | undefined): string {
  const value = (raw ?? '').trim();
  if (!value) return '';
  // A trailing slash plus our own "/" would produce "https://x//og.png".
  return value.replace(/\/+$/, '');
}

export function applySiteUrl(html: string, siteUrl: string): string {
  const base = normalizeSiteUrl(siteUrl);
  return html.split(SITE_URL_TOKEN).join(base);
}

export function seoMetaPlugin(options: { siteUrl?: string; warn?: (message: string) => void } = {}): Plugin {
  let isBuild = false;
  let resolved = normalizeSiteUrl(options.siteUrl ?? process.env.VITE_SITE_URL);

  return {
    name: 'pulsar-seo-meta',
    configResolved(config) {
      isBuild = config.command === 'build';
      // `define`d values from a mode file land here too; env is the usual path.
      resolved = resolved || normalizeSiteUrl(config.env?.VITE_SITE_URL);
    },
    transformIndexHtml(html: string) {
      if (isBuild && !resolved) {
        const warn = options.warn ?? ((message: string) => console.warn(message));
        warn(
          '[seo] VITE_SITE_URL is not set: og:url / og:image / twitter:image are ' +
            'relative. Most crawlers need an absolute URL — set VITE_SITE_URL to the ' +
            'public origin (e.g. https://app.example.com) before deploying.',
        );
      }
      return applySiteUrl(html, resolved);
    },
  };
}
