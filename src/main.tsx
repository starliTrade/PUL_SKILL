import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { EventEmitter } from 'events';
import App from './App.tsx';
import { LanguageProvider } from './i18n/LanguageContext';
import './index.css';

// Safety polyfills and error interceptors for Web3 libraries in browser and preview environments
if (typeof window !== 'undefined') {
  // Prevent unhandled WalletConnect EventEmitter error crashes when relay closes with code 3000 (origin not allowed)
  try {
    const origEmit = EventEmitter.prototype.emit;
    EventEmitter.prototype.emit = function (type: string, ...args: any[]) {
      if (type === 'error') {
        const err = args[0];
        const msg = String(typeof err === 'string' ? err : (err?.message || '')).toLowerCase();
        if (
          msg.includes('3000') ||
          msg.includes('origin not allowed') ||
          msg.includes('websocket connection closed') ||
          msg.includes('unauthorized')
        ) {
          console.warn('[Pulsar Web3] Safely caught WalletConnect relay WebSocket origin error:', err?.message || err);
          return false;
        }
      }
      return origEmit.apply(this, [type, ...args] as any);
    };
  } catch {}

  // Intercept window uncaught errors from background WebSockets
  window.addEventListener('error', (event: ErrorEvent) => {
    const rawMsg = event?.message || (event?.error && event.error.message) || '';
    const msg = String(rawMsg).toLowerCase();
    if (
      msg.includes('3000') ||
      msg.includes('origin not allowed') ||
      msg.includes('websocket connection closed') ||
      msg.includes('unauthorized')
    ) {
      console.warn('[Pulsar Web3] Intercepted background WebSocket origin error:', rawMsg);
      event.preventDefault();
      event.stopImmediatePropagation();
      return true;
    }
  }, true);

  // Intercept window unhandled promise rejections from background WebSockets
  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const reason = event?.reason;
    const rawMsg = typeof reason === 'string' ? reason : (reason?.message || '');
    const msg = String(rawMsg).toLowerCase();
    if (
      msg.includes('3000') ||
      msg.includes('origin not allowed') ||
      msg.includes('websocket connection closed') ||
      msg.includes('unauthorized')
    ) {
      console.warn('[Pulsar Web3] Intercepted background WebSocket unhandled rejection:', rawMsg);
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

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
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
);

