/**
 * Web3 Mobile Deep Linking & Native Wallet Session Authorization
 * Pure WalletConnect session approval: opens the native wallet ONLY to prompt for
 * session connection/signing permission, keeping the dApp running entirely in this browser.
 */

export const isMobileDevice = (): boolean => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const isTouch = Boolean(
    'ontouchstart' in window ||
    navigator.maxTouchPoints > 0
  );
  const isMobileUa = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  return isMobileUa || (isTouch && window.innerWidth <= 820);
};

export const isInAppBrowser = (): boolean => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const hasInjectedEth = Boolean((window as any).ethereum);
  const isWalletUa = /MetaMaskMobile|Trust|Phantom|CoinbaseWallet|Rainbow|TokenPocket|imToken|SafePal|OKApp/i.test(ua);
  return hasInjectedEth || isWalletUa;
};

export const isIframeOrSandboxed = (): boolean => {
  if (typeof window === 'undefined') return false;
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
};

/**
 * Direct Native Application URL Schemes:
 * Directly invokes the wallet app's native activity/view for session permission approval.
 * Bypasses intermediate web redirectors (like Branch.io) that can drop URI parameters on Android.
 */
export const getNativeSchemeUri = (walletId: string, wcUri: string): string => {
  if (!wcUri || wcUri.trim().length === 0) return '';
  const encodedUri = encodeURIComponent(wcUri.trim());
  const id = walletId.toLowerCase();
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
      return `phantom://ul/v1/connect?uri=${encodedUri}`;
    case 'okx':
      return `okx://wallet/wc?uri=${encodedUri}`;
    case 'bitget':
      return `bitkeep://wc?uri=${encodedUri}`;
    case 'zerion':
      return `zerion://wc?uri=${encodedUri}`;
    default:
      return `wc:${encodedUri}`;
  }
};

/**
 * Universal Links for WalletConnect:
 * Fallback HTTPS links that instruct the OS to open the installed app for permission confirmation.
 */
export const getWalletConnectDeepLink = (walletId: string, wcUri: string): string => {
  if (!wcUri || wcUri.trim().length === 0) return '';
  const encodedUri = encodeURIComponent(wcUri.trim());
  const id = walletId.toLowerCase();

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
      return `https://phantom.app/ul/v1/connect?uri=${encodedUri}`;
    case 'okx':
      return `okx://wallet/wc?uri=${encodedUri}`;
    case 'bitget':
      return `bitkeep://wc?uri=${encodedUri}`;
    case 'zerion':
      return `https://wallet.zerion.io/wc?uri=${encodedUri}`;
    default:
      return `https://metamask.app.link/wc?uri=${encodedUri}`;
  }
};

/**
 * Trigger native mobile wallet session handoff:
 * Direct navigation via window.location.href opens the native wallet app directly to the
 * connection confirmation screen without opening empty browser tabs or unloading the dApp.
 */
export const triggerMobileWalletHandoff = (nativeScheme?: string, universalLink?: string): void => {
  if (typeof window === 'undefined') return;

  // Prefer direct native scheme (e.g. metamask://wc?uri=... or trust://wc?uri=...)
  // because native schemes deliver the URI directly to the wallet's permission prompt.
  const target =
    nativeScheme && nativeScheme.trim().length > 0 && nativeScheme !== '#'
      ? nativeScheme.trim()
      : universalLink && universalLink.trim().length > 0 && universalLink !== '#'
      ? universalLink.trim()
      : '';

  if (!target) {
    console.warn('[Pulsar Web3] Cannot trigger handoff: target is empty');
    return;
  }

  // Guard: NEVER trigger wallet with an empty uri parameter
  if (
    target.endsWith('wc?uri=') ||
    target.endsWith('wc?uri') ||
    target.endsWith('connect?uri=') ||
    target.endsWith('connect?uri')
  ) {
    console.warn('[Pulsar Web3] Aborted handoff: WalletConnect URI parameter is empty');
    return;
  }

  try {
    // Calling window.location.href with custom scheme lets mobile OS open the wallet app directly
    // and keeps the current browser window active in the background.
    window.location.href = target;
  } catch {
    try {
      window.location.assign(target);
    } catch (err) {
      console.warn('[Pulsar Web3] Native handoff error:', err);
    }
  }
};
