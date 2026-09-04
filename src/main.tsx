import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { EventEmitter } from 'events';
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
      msg.includes('relay.walletconnect')
    );
  };

  // Prevent unhandled WalletConnect EventEmitter error crashes when relay closes or rejects
  try {
    const origEmit = EventEmitter.prototype.emit;
    EventEmitter.prototype.emit = function (type: string, ...args: any[]) {
      if (type === 'error' && isIgnorableBackgroundError(args[0])) {
        console.warn('[Pulsar Web3] Handled background relay event:', args[0]?.message || args[0]);
        return false;
      }
      return origEmit.apply(this, [type, ...args] as any);
    };
  } catch {}

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
  try {
    if (typeof window.fetch === 'function' && !Object.isExtensible(window.fetch)) {
      const origFetch = window.fetch;
      const extensibleFetch = function (this: any, ...args: any[]) {
        return origFetch.apply(this === extensibleFetch ? window : this, args as any);
      };
      Object.setPrototypeOf(extensibleFetch, origFetch);
      window.fetch = extensibleFetch as any;
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

