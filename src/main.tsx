import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import { LanguageProvider } from './i18n/LanguageContext';
import { Web3Provider } from './hooks/useWeb3';
import './index.css';

// Safety polyfills and error interceptors for Web3 libraries in browser and preview environments
if (typeof window !== 'undefined') {
  const isIgnorableBackgroundError = (raw: any): boolean => {
    const msg = String(
      typeof raw === 'string'
        ? raw
        : raw?.message || raw?.error?.message || raw?.reason?.message || raw?.reason || ''
    ).toLowerCase();

    return (
      msg.includes('3000') ||
      msg.includes('403') ||
      msg.includes('http status code') ||
      msg.includes('forbidden') ||
      msg.includes('origin not allowed') ||
      msg.includes('websocket connection closed') ||
      msg.includes('failed to connect to websocket') ||
      msg.includes('unauthorized') ||
      msg.includes('walletconnect') ||
      msg.includes('relay.walletconnect') ||
      msg.includes('attempted to assign to readonly property') ||
      msg.includes('which has only a getter') ||
      msg.includes('cannot assign to read only property')
    );
  };

  // Intercept window uncaught errors from background WebSockets / Relay
  window.addEventListener(
    'error',
    (event: ErrorEvent) => {
      if (isIgnorableBackgroundError(event)) {
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

