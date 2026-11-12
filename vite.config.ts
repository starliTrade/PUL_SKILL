import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';
import {seoMetaPlugin} from './vite-plugin-seo';

export default defineConfig(() => {
  return {
    // Audit M-20: fills the absolute URL for og:/twitter: metadata at build time.
    plugins: [react(), tailwindcss(), seoMetaPlugin()],
    resolve: {
      alias: [
        { find: '@', replacement: path.resolve(__dirname, '.') },
        { find: /^cross-fetch(\/.*)?$/, replacement: path.resolve(__dirname, 'src/shims/cross-fetch.ts') },
      ],
    },
    optimizeDeps: {
      exclude: ['cross-fetch'],
    },
    server: {
        port: 3000,
        strictPort: true,
        host: '0.0.0.0',
        // Audit 8.16: this was `allowedHosts: true`, which accepts ANY Host
        // header — the DNS-rebinding vector Vite's check exists to close (a page
        // on any origin can reach the dev server through a rebound hostname).
        //
        // It is now an explicit allowlist. A proxied preview needs its own host,
        // so set VITE_ALLOWED_HOSTS to a comma-separated list, or to `*` to
        // restore the old blanket behaviour knowingly. This only affects the DEV
        // server; production builds are unaffected.
        allowedHosts: (() => {
          const raw = process.env.VITE_ALLOWED_HOSTS;
          if (!raw) return ['localhost', '127.0.0.1', '.letta.com', '.trycloudflare.com'];
          if (raw.trim() === '*') return true as const;
          return raw.split(',').map((h) => h.trim()).filter(Boolean);
        })(),
      },
  };
});
