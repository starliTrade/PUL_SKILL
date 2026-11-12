import {StrictMode} from 'react';
import { watchRegistration } from './lib/swUpdate';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import { LanguageProvider } from './i18n/LanguageContext';
import { initErrorMonitoring } from './lib/monitoring';
import './index.css';

// P2.4 — error monitoring. No-ops unless VITE_SENTRY_DSN is configured.
// Audit M44: lazy — the Sentry SDK is only fetched when a DSN exists.
void initErrorMonitoring();

// Boot hygiene: purge orphaned/stale WalletConnect proposal keys.
// NOTE (P0.8): the previous console.error / window.onerror interception that
// silenced WalletConnect & relay noise is intentionally gone — real errors
// must surface so they can actually be fixed (and later reported to Sentry).
if (typeof window !== 'undefined') {
  try {
    if (window.localStorage) {
      // Iterate BACKWARDS: forward loops skip the entry after each removal
      // (localStorage indices shift under the cursor as keys are removed).
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i);
        if (k && k.startsWith('wc@2:') && k.includes('proposal')) {
          localStorage.removeItem(k);
        }
      }
    }
  } catch {}

  try {
    if (typeof (window as any).global === 'undefined') {
      Object.defineProperty(window, 'global', {
        value: window,
        writable: true,
        configurable: true,
      });
    }
  } catch {}
  try {
    if (typeof (window as any).process === 'undefined') {
      Object.defineProperty(window, 'process', {
        value: { env: {}, browser: true, version: '', versions: {}, platform: 'browser' },
        writable: true,
        configurable: true,
      });
    }
  } catch {}
}

// Plan item 11.3 / G15: register the service worker so the app is installable
// and opens offline. `public/sw.js` NEVER caches /api — a stale balance is a lie
// about money — so this only affects the static shell.
//
// Only in a production build: a service worker in dev serves stale modules and
// makes every edit look like it did not apply.
const _env = (import.meta as unknown as { env?: { PROD?: boolean } }).env ?? {};
if (_env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        // Audit M-18: a new build WAITS. The banner asks the player, the worker
        // swaps on request, and this listener performs exactly one reload.
        let reloading = false;
        watchRegistration(
          registration as unknown as Parameters<typeof watchRegistration>[0],
          Boolean(navigator.serviceWorker.controller),
          () => {
            if (reloading) return;
            reloading = true;
            window.location.reload();
          },
        );
      })
      .catch(() => {
        // A failed registration must never break the app; it only costs
        // installability.
      });
  });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
);
