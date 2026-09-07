import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import { LanguageProvider } from './i18n/LanguageContext';
import { Web3Provider } from './hooks/useWeb3';
import './index.css';

// Safety polyfills and error interceptors for Web3 libraries in browser and preview environments
if (typeof window !== 'undefined') {
  // Purge orphaned/stale WalletConnect proposal keys on boot
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

  const isIgnorableBackgroundError = (raw: any): boolean => {
    let msg = '';
    try {
      if (typeof raw === 'string') {
        msg = raw;
      } else if (raw && typeof raw === 'object') {
        msg = raw.message || raw?.error?.message || raw?.reason?.message || raw?.reason || raw?.msg || JSON.stringify(raw) || '';
      } else {
        msg = String(raw || '');
      }
    } catch {
      msg = String(raw || '');
    }

    const lower = msg.toLowerCase();
    return (
      lower.includes('no matching key') ||
      lower.includes('proposal:') ||
      lower.includes('3000') ||
      lower.includes('403') ||
      lower.includes('http status code') ||
      lower.includes('forbidden') ||
      lower.includes('origin not allowed') ||
      lower.includes('websocket connection closed') ||
      lower.includes('failed to connect to websocket') ||
      lower.includes('unauthorized') ||
      lower.includes('walletconnect') ||
      lower.includes('relay.walletconnect') ||
      lower.includes('attempted to assign to readonly property') ||
      lower.includes('which has only a getter') ||
      lower.includes('cannot assign to read only property')
    );
  };

  if (typeof console !== 'undefined' && console.error) {
    const originalConsoleError = console.error;
    console.error = (...args: any[]) => {
      if (args.some((arg) => isIgnorableBackgroundError(arg))) {
        if (console.warn) {
          console.warn('[Pulsar Web3 Intercepted]:', ...args);
        }
        return;
      }
      originalConsoleError.apply(console, args);
    };
  }

  // Intercept window uncaught errors from background WebSockets / Relay
  window.addEventListener(
    'error',
    (event: ErrorEvent) => {
      if (isIgnorableBackgroundError(event) || isIgnorableBackgroundError(event.error)) {
        console.warn('[Pulsar Web3] Intercepted background network error:', event.message);
        event.preventDefault();
        event.stopImmediatePropagation();
        return true;
      }
    },
    true
  );

  // Intercept window unhandled promise rejections from background WebSockets / Relay
  window.addEventListener(
    'unhandledrejection',
    (event: PromiseRejectionEvent) => {
      if (isIgnorableBackgroundError(event.reason)) {
        console.warn('[Pulsar Web3] Intercepted background unhandled rejection:', event.reason);
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true
  );

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
    <Web3Provider>
      <LanguageProvider>
        <App />
      </LanguageProvider>
    </Web3Provider>
  </StrictMode>,
);

