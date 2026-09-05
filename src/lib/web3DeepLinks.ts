/**
 * Mobile WalletConnect handoff (iOS Safari / Chrome first).
 *
 * Standard Web3 behavior:
 * - The dApp stays in the system browser (Safari / Chrome).
 * - Tapping a wallet opens the native app only to approve the WC session.
 * - After approval, iOS returns to the same browser tab.
 *
 * Never use dapp-browser links (metamask.app.link/dapp/..., Trust open_url, etc.).
 * Those load this site inside the wallet WebView.
 */

export const isMobileDevice = (): boolean => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const isTouch = Boolean('ontouchstart' in window || navigator.maxTouchPoints > 0);
  const isMobileUa = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  return isMobileUa || (isTouch && window.innerWidth <= 820);
};

export const isIOS = (): boolean => {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const iOSDevice = /iPad|iPhone|iPod/i.test(ua);
  const iPadOs = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  return iOSDevice || iPadOs;
};

export const isAndroid = (): boolean => {
  if (typeof navigator === 'undefined') return false;
  return /Android/i.test(navigator.userAgent || '');
};

/** True only inside a wallet's own WebView — not Safari, Chrome, or desktop extensions. */
export const isWalletInAppBrowser = (): boolean => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const walletUa =
    /MetaMaskMobile|MetaMask/i.test(ua) && /Mobile/i.test(ua)
      ? /MetaMaskMobile/i.test(ua)
      : false;
  const otherWalletUa =
    /TrustWallet|Trust\/|CoinbaseWallet|CBWallet|Rainbow\/|Phantom\/|imToken|TokenPocket|OkApp|OKApp|BitKeep|Zerion/i.test(
      ua
    );
  const hasInjected = Boolean((window as any).ethereum || (window as any).trustwallet);
  return hasInjected && (walletUa || otherWalletUa);
};

export const isInAppBrowser = (): boolean => isWalletInAppBrowser();

export const isIframeOrSandboxed = (): boolean => {
  if (typeof window === 'undefined') return false;
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
};

const normalizeWalletId = (walletId: string): string => walletId.toLowerCase().replace(/[\s_-]/g, '');

/**
 * Native custom-scheme WC links. These prompt session approval in the wallet app
 * and return to Safari/Chrome instead of opening a wallet WebView.
 */
export const getNativeSchemeUri = (walletId: string, wcUri: string): string => {
  if (!wcUri || wcUri.trim().length === 0) return '';
  const encodedUri = encodeURIComponent(wcUri.trim());
  const id = normalizeWalletId(walletId);

  switch (id) {
    case 'metamask':
      return `metamask://wc?uri=${encodedUri}`;
    case 'trust':
    case 'trustwallet':
      return `trust://wc?uri=${encodedUri}`;
    case 'rainbow':
      return `rainbow://wc?uri=${encodedUri}`;
    case 'coinbase':
    case 'coinbasewallet':
      return `cbwallet://wc?uri=${encodedUri}`;
    case 'phantom':
      return `phantom://wc?uri=${encodedUri}`;
    case 'okx':
    case 'okxwallet':
      return `okx://wallet/wc?uri=${encodedUri}`;
    case 'bitget':
    case 'bitgetwallet':
      return `bitkeep://wc?uri=${encodedUri}`;
    case 'zerion':
      return `zerion://wc?uri=${encodedUri}`;
    case 'walletconnect':
      return wcUri.trim();
    default:
      return `metamask://wc?uri=${encodedUri}`;
  }
};

/**
 * HTTPS universal links — fallback only when the native scheme does not open.
 * These still target the WC approval route, not the in-app dapp browser.
 */
export const getWalletConnectDeepLink = (walletId: string, wcUri: string): string => {
  if (!wcUri || wcUri.trim().length === 0) return '';
  const encodedUri = encodeURIComponent(wcUri.trim());
  const id = normalizeWalletId(walletId);

  switch (id) {
    case 'metamask':
      return `https://metamask.app.link/wc?uri=${encodedUri}`;
    case 'trust':
    case 'trustwallet':
      return `https://link.trustwallet.com/wc?uri=${encodedUri}`;
    case 'rainbow':
      return `https://rainbow.me/wc?uri=${encodedUri}`;
    case 'coinbase':
    case 'coinbasewallet':
      return `https://go.cb-w.com/wc?uri=${encodedUri}`;
    case 'phantom':
      return `https://phantom.app/ul/v1/wc?uri=${encodedUri}`;
    case 'okx':
    case 'okxwallet':
      return `okx://wallet/wc?uri=${encodedUri}`;
    case 'bitget':
    case 'bitgetwallet':
      return `bitkeep://wc?uri=${encodedUri}`;
    case 'zerion':
      return `https://wallet.zerion.io/wc?uri=${encodedUri}`;
    default:
      return wcUri.trim();
  }
};

const isEmptyWcTarget = (target: string): boolean =>
  target.endsWith('wc?uri=') ||
  target.endsWith('wc?uri') ||
  target.endsWith('connect?uri=') ||
  target.endsWith('connect?uri');

/**
 * Open the native wallet from a user gesture (tap).
 * iOS: custom scheme via <a>.click() so Safari is not replaced by a wallet WebView.
 */
export const openWalletConnectInNativeApp = (walletId: string, wcUri: string): boolean => {
  if (typeof window === 'undefined' || !wcUri) return false;

  const native = getNativeSchemeUri(walletId, wcUri);
  const target = native || wcUri.trim();
  if (!target || isEmptyWcTarget(target)) return false;

  try {
    if (isIOS()) {
      const anchor = document.createElement('a');
      anchor.href = target;
      anchor.rel = 'noreferrer';
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => {
        try {
          anchor.remove();
        } catch {
          /* ignore */
        }
      }, 1500);
      return true;
    }

    window.location.href = target;
    return true;
  } catch (err) {
    console.warn('[Pulsar Web3] Native wallet open failed:', err);
    return false;
  }
};

export const triggerMobileWalletHandoff = (nativeScheme?: string, universalLink?: string): void => {
  if (typeof window === 'undefined') return;

  const target =
    nativeScheme && nativeScheme.trim().length > 0 && nativeScheme !== '#'
      ? nativeScheme.trim()
      : universalLink && universalLink.trim().length > 0 && universalLink !== '#'
        ? universalLink.trim()
        : '';

  if (!target || isEmptyWcTarget(target)) {
    console.warn('[Pulsar Web3] Cannot trigger handoff: empty WalletConnect URI');
    return;
  }

  try {
    if (isIOS()) {
      const anchor = document.createElement('a');
      anchor.href = target;
      anchor.rel = 'noreferrer';
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => anchor.remove(), 1500);
      return;
    }
    window.location.href = target;
  } catch {
    try {
      window.location.assign(target);
    } catch (err) {
      console.warn('[Pulsar Web3] Native handoff error:', err);
    }
  }
};
