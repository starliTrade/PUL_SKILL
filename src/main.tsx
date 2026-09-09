import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import { LanguageProvider } from './i18n/LanguageContext';
import { initErrorMonitoring } from './lib/monitoring';
import './index.css';

// P2.4 — error monitoring. No-ops unless VITE_SENTRY_DSN is configured.
initErrorMonitoring();

// Boot hygiene: purge orphaned/stale WalletConnect proposal keys.
// NOTE (P0.8): the previous console.error / window.onerror interception that
// silenced WalletConnect & relay noise is intentionally gone — real errors
// must surface so they can actually be fixed (and later reported to Sentry).
if (typeof window !== 'undefined') {
  try {
    if (window.localStorage) {
      for (let i = 0; i < localStorage.length; i++) {
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
);
