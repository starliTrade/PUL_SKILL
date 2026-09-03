/**
 * Web3 Mobile Deep Linking & Environment Detection
 * Provides OpenSea/Uniswap-grade seamless mobile wallet connectivity via WalletConnect.
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
 * Universal Links for WalletConnect: opens native wallet directly to issue permission/sign.
 * Does NOT open the in-app browser; directly prompts for connection approval.
 */
export const getWalletConnectDeepLink = (walletId: string, wcUri: string): string => {
  const encodedUri = encodeURIComponent(wcUri);
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
 * Direct DApp Browser Links:
 * Opens the current website DIRECTLY inside the mobile wallet's native in-app Web3 browser.
 * Inside the native wallet browser, window.ethereum is already present and connects instantly with 1 tap.
 */
export const getDAppBrowserDeepLink = (walletId: string, targetUrl?: string): string => {
  const fullUrl =
    targetUrl ||
    (typeof window !== 'undefined'
      ? window.location.origin + window.location.pathname
      : 'https://pulsar.arena');

  const cleanWithoutProtocol = fullUrl.replace(/^https?:\/\//i, '');
  const encodedFullUrl = encodeURIComponent(fullUrl);
  const id = walletId.toLowerCase();

  switch (id) {
    case 'metamask':
      // MetaMask expects URL without https://
      return `https://metamask.app.link/dapp/${cleanWithoutProtocol}`;
    case 'trust':
    case 'trustwallet':
      return `https://link.trustwallet.com/open_url?coin_id=60&url=${encodedFullUrl}`;
    case 'coinbase':
    case 'coinbasewallet':
      return `https://go.cb-w.com/dapp?cb_url=${encodedFullUrl}`;
    case 'phantom':
      return `https://phantom.app/ul/browse/${encodedFullUrl}?ref=${encodedFullUrl}`;
    case 'okx':
      return `okx://wallet/dapp/url?dappUrl=${encodedFullUrl}`;
    case 'rainbow':
      return `https://rainbow.me/dapp?url=${encodedFullUrl}`;
    case 'bitget':
      return `https://bkcode.vip?action=dapp&url=${encodedFullUrl}`;
    default:
      return `https://metamask.app.link/dapp/${cleanWithoutProtocol}`;
  }
};

/**
 * Native Custom URL Schemes as fallback for specific mobile apps
 */
export const getNativeSchemeUri = (walletId: string, wcUri: string): string => {
  const encodedUri = encodeURIComponent(wcUri);
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
      return `phantom://wc?uri=${encodedUri}`;
    default:
      return `wc:${encodedUri}`;
  }
};

/**
 * Trigger native mobile wallet handoff
 */
export const triggerMobileWalletHandoff = (deepLink: string): void => {
  if (typeof window === 'undefined') return;
  try {
    let topAttempted = false;
    try {
      if (window.top && window.top !== window.self) {
        window.top.location.href = deepLink;
        topAttempted = true;
      }
    } catch {}

    if (!topAttempted) {
      window.location.href = deepLink;
    }
  } catch (err) {
    console.warn('Handoff error:', err);
  }
};
