import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  Wallet,
  X,
  ChevronRight,
  ChevronDown,
  AlertCircle,
  ExternalLink,
  CheckCircle2,
  Loader2,
  Copy,
  LogOut,
  ArrowDownLeft,
  Sparkles,
  HelpCircle,
  QrCode,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { usePulsarStore } from '../store/usePulsarStore';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';
import { eip6963Manager, EIP6963ProviderDetail } from '../lib/eip6963';
import {
  realWeb3Manager,
  getWalletConnectProjectId,
} from '../lib/realWeb3';
import {
  isMobileDevice,
  isIframeOrSandboxed,
  isWalletInAppBrowser,
  getNativeSchemeUri,
  getWalletConnectDeepLink,
  openWalletConnectInNativeApp,
} from '../lib/web3DeepLinks';

// -------------------------------------------------------------
// Pixel-Perfect SVG Wallet Icons (OpenSea Standard)
// -------------------------------------------------------------
const MetaMaskLogo = () => (
  <svg viewBox="0 0 318.6 318.6" className="w-6 h-6 shrink-0">
    <polygon fill="#E2761B" stroke="#E2761B" strokeLinecap="round" strokeLinejoin="round" points="274.1 35.5 174.6 109.4 193 65.8 274.1 35.5"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="44.4 35.5 124.6 66.2 143.8 109.8 44.4 35.5"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="238.3 206.8 211.8 247.4 268.5 263 284.8 207.7 238.3 206.8"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="33.9 207.7 50.1 263 106.8 247.4 80.3 206.8 33.9 207.7"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="103.6 138.2 87.8 162.3 144.1 164.6 142.4 104.1 103.6 138.2"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="214.9 138.2 175.9 103.4 174.6 164.6 230.8 162.3 214.9 138.2"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="106.8 247.4 140.6 230.9 111.4 208.1 106.8 247.4"/>
    <polygon fill="#E4761B" stroke="#E4761B" strokeLinecap="round" strokeLinejoin="round" points="177.9 230.9 211.8 247.4 207.1 208.1 177.9 230.9"/>
    <polygon fill="#D7C1B3" stroke="#D7C1B3" strokeLinecap="round" strokeLinejoin="round" points="211.8 247.4 177.9 230.9 180.6 253 180.3 262.3 211.8 247.4"/>
    <polygon fill="#D7C1B3" stroke="#D7C1B3" strokeLinecap="round" strokeLinejoin="round" points="106.8 247.4 138.3 262.3 138.1 253 140.6 230.9 106.8 247.4"/>
    <polygon fill="#233447" stroke="#233447" strokeLinecap="round" strokeLinejoin="round" points="138.8 193.5 110.6 185.2 130.5 176.1 138.8 193.5"/>
    <polygon fill="#233447" stroke="#233447" strokeLinecap="round" strokeLinejoin="round" points="179.7 193.5 188.1 176.1 208 185.2 179.7 193.5"/>
    <polygon fill="#CD6116" stroke="#CD6116" strokeLinecap="round" strokeLinejoin="round" points="106.8 247.4 111.6 206.8 80.3 207.5 106.8 247.4"/>
    <polygon fill="#CD6116" stroke="#CD6116" strokeLinecap="round" strokeLinejoin="round" points="207 206.8 211.8 247.4 238.3 207.5 207 206.8"/>
    <polygon fill="#CD6116" stroke="#CD6116" strokeLinecap="round" strokeLinejoin="round" points="230.8 162.3 174.6 164.6 179.8 193.5 188.1 176.1 208 185.2 230.8 162.3"/>
    <polygon fill="#CD6116" stroke="#CD6116" strokeLinecap="round" strokeLinejoin="round" points="110.6 185.2 130.5 176.1 138.8 193.5 144.1 164.6 87.8 162.3 110.6 185.2"/>
    <polygon fill="#E4751F" stroke="#E4751F" strokeLinecap="round" strokeLinejoin="round" points="87.8 162.3 111.4 208.1 110.6 185.2 87.8 162.3"/>
    <polygon fill="#E4751F" stroke="#E4751F" strokeLinecap="round" strokeLinejoin="round" points="208 185.2 207.1 208.1 230.8 162.3 208 185.2"/>
    <polygon fill="#E4751F" stroke="#E4751F" strokeLinecap="round" strokeLinejoin="round" points="144.1 164.6 138.8 193.5 145.4 227.6 146.9 164.7 144.1 164.6"/>
    <polygon fill="#E4751F" stroke="#E4751F" strokeLinecap="round" strokeLinejoin="round" points="174.6 164.6 171.8 164.7 173.3 227.6 179.8 193.5 174.6 164.6"/>
    <polygon fill="#F6851B" stroke="#F6851F" strokeLinecap="round" strokeLinejoin="round" points="179.8 193.5 173.3 227.6 177.9 230.9 207.1 208.1 208 185.2 179.8 193.5"/>
    <polygon fill="#F6851B" stroke="#F6851F" strokeLinecap="round" strokeLinejoin="round" points="110.6 185.2 111.4 208.1 140.6 230.9 145.4 227.6 138.8 193.5 110.6 185.2"/>
    <polygon fill="#C0AD9E" stroke="#C0AD9E" strokeLinecap="round" strokeLinejoin="round" points="180.3 262.3 180.6 253 177.9 230.9 140.6 230.9 138.1 253 138.3 262.3 106.8 247.4 117.8 256.4 140.1 271.9 178.4 271.9 200.8 256.4 211.8 247.4 180.3 262.3"/>
    <polygon fill="#161616" stroke="#161616" strokeLinecap="round" strokeLinejoin="round" points="177.9 230.9 173.3 227.6 145.4 227.6 140.6 230.9 138.1 253 180.6 253 177.9 230.9"/>
    <polygon fill="#763D16" stroke="#763D16" strokeLinecap="round" strokeLinejoin="round" points="278.3 114.2 284.8 207.7 268.5 263 268.1 261.4 214.9 138.2 278.3 114.2"/>
    <polygon fill="#763D16" stroke="#763D16" strokeLinecap="round" strokeLinejoin="round" points="33.9 207.7 40.3 114.2 103.6 138.2 50.5 261.4 50.1 263 33.9 207.7"/>
    <polygon fill="#F6851B" stroke="#F6851B" strokeLinecap="round" strokeLinejoin="round" points="268.1 261.4 200.8 256.4 211.8 247.4 268.5 263 268.1 261.4"/>
    <polygon fill="#F6851B" stroke="#F6851B" strokeLinecap="round" strokeLinejoin="round" points="106.8 247.4 117.8 256.4 50.5 261.4 50.1 263 106.8 247.4"/>
  </svg>
);

const CoinbaseLogo = () => (
  <svg viewBox="0 0 32 32" className="w-6 h-6 shrink-0" fill="none">
    <circle cx="16" cy="16" r="16" fill="#0052FF"/>
    <path d="M16 6C10.477 6 6 10.477 6 16C6 21.523 10.477 26 16 26C21.523 26 26 21.523 26 16C26 10.477 21.523 6 16 6ZM13.5 13.5H18.5V18.5H13.5V13.5Z" fill="white"/>
  </svg>
);

const WalletConnectLogo = () => (
  <svg viewBox="0 0 32 32" className="w-6 h-6 shrink-0" fill="none">
    <circle cx="16" cy="16" r="16" fill="#3B99FC"/>
    <path d="M9.8 12.8C13.2 9.4 18.8 9.4 22.2 12.8L22.8 13.4C23 13.6 23 13.9 22.8 14.1L21.3 15.6C21.2 15.7 21 15.7 20.9 15.6L19.9 14.6C17.7 12.4 14.3 12.4 12.1 14.6L11.1 15.6C11 15.7 10.8 15.7 10.7 15.6L9.2 14.1C9 13.9 9 13.6 9.2 13.4L9.8 12.8ZM25.3 15.9L26.6 17.2C26.8 17.4 26.8 17.7 26.6 17.9L20.8 23.7C20.6 23.9 20.3 23.9 20.1 23.7L16 19.6C15.9 19.5 15.8 19.5 15.7 19.6L11.6 23.7C11.4 23.9 11.1 23.9 10.9 23.7L5.1 17.9C4.9 17.7 4.9 17.4 5.1 17.2L6.4 15.9C6.6 15.7 6.9 15.7 7.1 15.9L11.2 20C11.3 20.1 11.4 20.1 11.5 20L15.6 15.9C15.8 15.7 16.1 15.7 16.3 15.9L20.4 20C20.5 20.1 20.6 20.1 20.7 20L24.8 15.9C25 15.7 25.1 15.7 25.3 15.9Z" fill="white"/>
  </svg>
);

const PhantomLogo = () => (
  <svg viewBox="0 0 32 32" className="w-6 h-6 shrink-0" fill="none">
    <circle cx="16" cy="16" r="16" fill="#AB9FF2"/>
    <path d="M24 16C24 20.418 20.418 24 16 24C12.428 24 9.4 21.66 8.35 18.46C8.12 17.76 8 17.02 8 16.25C8 11.83 11.58 8.25 16 8.25C20.42 8.25 24 11.83 24 16Z" fill="#534BAE"/>
    <circle cx="13.5" cy="15.5" r="1.5" fill="#AB9FF2"/>
    <circle cx="18.5" cy="15.5" r="1.5" fill="#AB9FF2"/>
  </svg>
);

const TrustWalletLogo = () => (
  <svg viewBox="0 0 32 32" className="w-6 h-6 shrink-0" fill="none">
    <rect width="32" height="32" rx="8" fill="#0500FF"/>
    <path d="M16 6L8 10V16C8 21.5 11.4 26.6 16 28C20.6 26.6 24 21.5 24 16V10L16 6Z" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const RainbowLogo = () => (
  <svg viewBox="0 0 32 32" className="w-6 h-6 shrink-0" fill="none">
    <rect width="32" height="32" rx="8" fill="#0E1E38"/>
    <path d="M8 22C8 17.58 11.58 14 16 14C20.42 14 24 17.58 24 22" stroke="#FF4040" strokeWidth="2.5" strokeLinecap="round"/>
    <path d="M10.5 22C10.5 18.96 12.96 16.5 16 16.5C19.04 16.5 21.5 18.96 21.5 22" stroke="#FFBF00" strokeWidth="2.5" strokeLinecap="round"/>
    <path d="M13 22C13 20.34 14.34 19 16 19C17.66 19 19 20.34 19 22" stroke="#00E070" strokeWidth="2.5" strokeLinecap="round"/>
  </svg>
);

interface ConnectWalletProps {
  compact?: boolean;
  isOpen?: boolean;
  onClose?: () => void;
}

interface WalletItemDefinition {
  id: string;
  name: string;
  badge?: string;
  badgeType?: 'popular' | 'instant' | 'detected';
  logo: React.ReactNode;
  subtitle?: string;
}

export const ConnectWallet: React.FC<ConnectWalletProps> = ({
  compact = false,
  isOpen: controlledIsOpen,
  onClose: controlledOnClose,
}) => {
  const { t } = useLanguage();

  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : internalIsOpen;
  const setIsOpen = (open: boolean) => {
    setInternalIsOpen(open);
    if (!open && controlledOnClose) {
      controlledOnClose();
    }
  };

  const [mounted, setMounted] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [copiedAddr, setCopiedAddr] = useState(false);
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [depositAmountInput, setDepositAmountInput] = useState('10');
  const [depositStatusMsg, setDepositStatusMsg] = useState<string | null>(null);
  const [connectingWalletId, setConnectingWalletId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [eip6963Providers, setEip6963Providers] = useState<EIP6963ProviderDetail[]>([]);
  const [activeHandoff, setActiveHandoff] = useState<{
    walletId: string;
    walletName: string;
    deepLink: string;
    nativeScheme?: string;
    uri: string;
  } | null>(null);
  const [showHandoffQr, setShowHandoffQr] = useState(false);
  const [copiedUri, setCopiedUri] = useState(false);

  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const {
    wallet,
    stats,
    connectWallet,
    connectEIP6963,
    cancelPendingConnect,
    disconnectWallet,
    refreshBalance,
  } = usePulsarStore();

  const [isRefreshingBalance, setIsRefreshingBalance] = useState(false);

  const wcUriRef = useRef('');

  useEffect(() => {
    setMounted(true);
    const unsubProviders = eip6963Manager.subscribe((providers) => {
      setEip6963Providers([...providers]);
    });
    const unsubUri = realWeb3Manager.onWcUri((uri) => {
      wcUriRef.current = uri;
    });
    return () => {
      unsubProviders();
      unsubUri();
    };
  }, []);

  useEffect(() => {
    if (!isOpen || wallet.connected) {
      return;
    }
    if (isMobileDevice() && !isWalletInAppBrowser()) {
      realWeb3Manager.prepareWalletConnect();
    }
  }, [isOpen, wallet.connected]);

  // Auto-close modal as soon as wallet connection handshake completes successfully
  useEffect(() => {
    if (wallet.connected && isOpen) {
      setConnectingWalletId(null);
      setActiveHandoff(null);
      setErrorMessage(null);
      setIsOpen(false);
    }
  }, [wallet.connected, isOpen]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node)
      ) {
        setDropdownOpen(false);
      }
    };

    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [dropdownOpen]);

  const handleCopyAddress = () => {
    const addr = wallet.fullAddress || wallet.address;
    if (addr) {
      sounds.playClick();
      navigator.clipboard.writeText(addr);
      setCopiedAddr(true);
      setTimeout(() => setCopiedAddr(false), 2000);
    }
  };

  const handleCloseModal = () => {
    sounds.playClick();
    cancelPendingConnect();
    setConnectingWalletId(null);
    setActiveHandoff(null);
    setErrorMessage(null);
    setIsOpen(false);
  };

  const handleConnectWalletItem = async (walletId: string, walletName: string) => {
    setErrorMessage(null);
    sounds.playClick();

    const mobileBrowser = isMobileDevice() && !isWalletInAppBrowser();

    // 1. Desktop Browser Extensions (EIP-6963): Connect directly with 0 external relays!
    const matchedEip = eip6963Providers.find(
      (p) =>
        p.info.name.toLowerCase().includes(walletName.toLowerCase()) ||
        p.info.rdns.toLowerCase().includes(walletId.toLowerCase())
    );

    if (matchedEip && !mobileBrowser) {
      setConnectingWalletId(matchedEip.info.rdns);
      try {
        await connectEIP6963(matchedEip);
        sounds.playWin();
        setIsOpen(false);
        return;
      } catch (err: any) {
        sounds.playLoss();
        const inIframe = typeof window !== 'undefined' && window.self !== window.top;
        if (inIframe) {
          console.warn('[ConnectWallet] Extension restricted in iframe, falling back to WalletConnect:', err);
          setErrorMessage(
            err?.message || 'Injected extension is restricted in preview iframes. Generating WalletConnect pairing...'
          );
        } else {
          setErrorMessage(err?.message || 'Injected wallet connection failed.');
          setConnectingWalletId(null);
          return;
        }
      }
    }

    // 2. In-App Mobile Browser (e.g. running inside MetaMask / Trust Wallet internal browser):
    if (isWalletInAppBrowser()) {
      setConnectingWalletId(walletId);
      try {
        await connectWallet(walletId);
        sounds.playWin();
        setIsOpen(false);
        return;
      } catch (err: any) {
        if (err?.message?.includes('cancelled') || err?.message?.includes('rejected')) {
          sounds.playLoss();
          setErrorMessage('Connection request was cancelled in your wallet.');
          setConnectingWalletId(null);
          return;
        }
      }
    }

    // 3. Mobile System Browser (Safari / Chrome) or Desktop fallback without extension:
    const activePid = getWalletConnectProjectId();
    if (!activePid || activePid.length < 16) {
      sounds.playLoss();
      setErrorMessage(
        'WalletConnect service is initializing. Please try connecting again.'
      );
      setConnectingWalletId(null);
      return;
    }

    const existingUri = wcUriRef.current || realWeb3Manager.lastWcUri || '';
    const nativeScheme = existingUri ? getNativeSchemeUri(walletId, existingUri) : '';
    const deepLink = existingUri ? getWalletConnectDeepLink(walletId, existingUri) : '';

    setConnectingWalletId(walletId);
    setActiveHandoff({
      walletId,
      walletName,
      deepLink,
      nativeScheme,
      uri: existingUri,
    });
    setShowHandoffQr(!isMobileDevice());

    if (mobileBrowser && existingUri) {
      openWalletConnectInNativeApp(walletId, existingUri);
    }

    // Fail-safe timer: NEVER leave the user spinning indefinitely on preparing!
    let uriEmitted = Boolean(existingUri);
    const pairingTimeout = setTimeout(() => {
      if (!uriEmitted && !wcUriRef.current) {
        setErrorMessage(
          'Wallet connection request timed out. Please check your wallet app and try again.'
        );
        setActiveHandoff(null);
        setConnectingWalletId(null);
      }
    }, 12000);

    try {
      await connectWallet(walletId, (uri, nextDeepLink, nextNativeScheme) => {
        uriEmitted = true;
        clearTimeout(pairingTimeout);
        wcUriRef.current = uri;
        setActiveHandoff({
          walletId,
          walletName,
          deepLink: nextDeepLink,
          nativeScheme: nextNativeScheme || getNativeSchemeUri(walletId, uri),
          uri,
        });
        if (mobileBrowser) {
          openWalletConnectInNativeApp(walletId, uri);
        }
      });
      clearTimeout(pairingTimeout);
      sounds.playWin();
      setActiveHandoff(null);
      setIsOpen(false);
    } catch (err: any) {
      clearTimeout(pairingTimeout);
      sounds.playLoss();
      const msg = err?.message || 'Connection failed';
      if (msg.includes('cancelled') || msg.includes('rejected')) {
        setErrorMessage('Connection request was cancelled in your wallet.');
      } else {
        setErrorMessage(msg);
      }
      setActiveHandoff(null);
    } finally {
      clearTimeout(pairingTimeout);
      setConnectingWalletId(null);
    }
  };

  const handleConfirmDeposit = async (e: React.FormEvent) => {
    e.preventDefault();
    sounds.playClick();
    setIsRefreshingBalance(true);
    try {
      await refreshBalance();
      setDepositStatusMsg('Balance updated from Polygon RPC');
    } catch {
      setDepositStatusMsg('Could not fetch balance. Check connection.');
    } finally {
      setIsRefreshingBalance(false);
      setTimeout(() => {
        setDepositStatusMsg(null);
      }, 2500);
    }
  };

  // Check which wallets are detected in the current window
  const isMetaMaskDetected =
    typeof window !== 'undefined' &&
    Boolean((window as any).ethereum?.isMetaMask || eip6963Providers.some((p) => p.info.name.toLowerCase().includes('metamask')));

  const isCoinbaseDetected =
    typeof window !== 'undefined' &&
    Boolean((window as any).coinbaseWalletExtension || (window as any).ethereum?.isCoinbaseWallet || eip6963Providers.some((p) => p.info.name.toLowerCase().includes('coinbase')));

  const isPhantomDetected =
    typeof window !== 'undefined' &&
    Boolean((window as any).phantom?.ethereum || (window as any).ethereum?.isPhantom || eip6963Providers.some((p) => p.info.name.toLowerCase().includes('phantom')));

  const isTrustDetected =
    typeof window !== 'undefined' &&
    Boolean((window as any).trustwallet || (window as any).ethereum?.isTrust || eip6963Providers.some((p) => p.info.name.toLowerCase().includes('trust')));

  // Standard OpenSea Wallet List
  const OPENSEA_WALLETS: WalletItemDefinition[] = [
    {
      id: 'MetaMask',
      name: 'MetaMask',
      badge: isMetaMaskDetected ? 'Detected' : 'Popular',
      badgeType: isMetaMaskDetected ? 'detected' : 'popular',
      logo: <MetaMaskLogo />,
      subtitle: isMetaMaskDetected ? 'Browser extension ready' : undefined,
    },
    {
      id: 'Coinbase',
      name: 'Coinbase Wallet',
      badge: isCoinbaseDetected ? 'Detected' : undefined,
      badgeType: isCoinbaseDetected ? 'detected' : undefined,
      logo: <CoinbaseLogo />,
    },
    {
      id: 'WalletConnect',
      name: 'WalletConnect',
      subtitle: 'Mobile Wallets & QR Code',
      logo: <WalletConnectLogo />,
    },
    {
      id: 'Phantom',
      name: 'Phantom',
      badge: isPhantomDetected ? 'Detected' : undefined,
      badgeType: isPhantomDetected ? 'detected' : undefined,
      logo: <PhantomLogo />,
    },
    {
      id: 'TrustWallet',
      name: 'Trust Wallet',
      badge: isTrustDetected ? 'Detected' : undefined,
      badgeType: isTrustDetected ? 'detected' : undefined,
      logo: <TrustWalletLogo />,
    },
    {
      id: 'Rainbow',
      name: 'Rainbow',
      logo: <RainbowLogo />,
    },
  ];

  // -------------------------------------------------------------
  // CONNECTED STATE: Sleek Profile Dropdown with Real On-Chain Vault
  // -------------------------------------------------------------
  if (wallet.connected) {
    const fullAddr = wallet.fullAddress || wallet.address || '';
    const shortDisplay =
      wallet.address && wallet.address.length > 10
        ? `${wallet.address.slice(0, 4)}...${wallet.address.slice(-3)}`
        : wallet.address || 'Connected';
    const userLabel = wallet.playerId ? wallet.playerId.split('#')[0] : shortDisplay;

    return (
      <div className="relative inline-block text-left" dir="ltr" style={{ direction: 'ltr' }}>
        {/* Compact User Chip in Navbar (Prevents clutter and mobile overflow) */}
        <button
          ref={triggerRef}
          type="button"
          data-user-badge="true"
          onClick={() => {
            sounds.playClick();
            setDropdownOpen(!dropdownOpen);
          }}
          className={cn(
            'user-badge-chip flex items-center gap-1.5 h-7.5 px-2.5 rounded-full border transition-all cursor-pointer select-none text-left',
            'border-emerald-500/30 bg-zinc-900/90 hover:bg-zinc-800/95 active:scale-95 text-xs shadow-[0_2px_8px_rgba(0,0,0,0.4)]',
            dropdownOpen && 'ring-1 ring-emerald-400 bg-zinc-800 border-emerald-400/60'
          )}
          style={{
            direction: 'ltr',
            fontFamily: "'JetBrains Mono', 'Plus Jakarta Sans', -apple-system, monospace",
          }}
          title={fullAddr}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0 shadow-[0_0_6px_#34d399]" />
          <span
            data-user-badge="true"
            className="user-badge-text font-mono font-semibold text-zinc-100 tracking-tight text-[11px] leading-none max-w-[80px] sm:max-w-[105px] truncate"
            style={{
              direction: 'ltr',
              fontFamily: "'JetBrains Mono', 'Plus Jakarta Sans', -apple-system, monospace",
              fontSize: '11px',
              fontWeight: 600,
              lineHeight: 1,
            }}
          >
            {userLabel}
          </span>
          <ChevronDown
            className={cn(
              'w-3 h-3 text-zinc-400 transition-transform duration-200 shrink-0 -ml-0.5',
              dropdownOpen && 'transform rotate-180 text-emerald-300'
            )}
          />
        </button>

        {/* Dropdown Menu */}
        <AnimatePresence>
          {dropdownOpen && (
            <motion.div
              ref={dropdownRef}
              initial={{ opacity: 0, y: 6, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.96 }}
              transition={{ duration: 0.15, ease: 'easeOut' }}
              className="absolute right-0 mt-2 w-[calc(100vw-32px)] sm:w-84 max-w-sm rounded-2xl bg-zinc-950/98 backdrop-blur-2xl border border-white/[0.12] shadow-[0_24px_60px_rgba(0,0,0,0.95),0_0_0_1px_rgba(255,255,255,0.06)] z-[99999] overflow-hidden p-3.5 text-left"
              style={{ direction: 'ltr' }}
            >
              {/* Header: Player Tag + Level + Network Indicator */}
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500/20 via-teal-500/10 to-sky-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-300 font-bold text-xs shrink-0 shadow-[0_0_14px_rgba(52,211,153,0.2)]">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs font-bold text-white truncate flex items-center gap-1.5" style={{ direction: 'ltr' }}>
                      <span
                        data-user-badge="true"
                        className="user-badge-text font-mono font-bold text-white text-xs truncate"
                        style={{
                          fontFamily: "'JetBrains Mono', 'Plus Jakarta Sans', monospace",
                          fontSize: '12px',
                          fontWeight: 700,
                        }}
                      >
                        {wallet.playerId || 'PULSAR Duelist'}
                      </span>
                      <span
                        data-user-badge="true"
                        className="text-[9.5px] font-mono font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.5 rounded shadow-sm"
                        style={{
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: '9.5px',
                        }}
                      >
                        Lv.{stats.level || 1}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-400 flex items-center gap-1.5 mt-0.5" style={{ direction: 'ltr' }}>
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block shadow-[0_0_6px_#34d399] animate-pulse" />
                      <span className="font-mono text-[10px] text-zinc-300 font-medium">Polygon PoS</span>
                      <span className="text-zinc-600">•</span>
                      <span className="font-mono text-[9.5px] text-zinc-400">Chain 137</span>
                    </div>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-[10px] font-mono text-zinc-300 bg-white/[0.05] px-2 py-0.5 rounded-md border border-white/[0.08] font-medium">
                    {wallet.provider || 'Web3'}
                  </span>
                </div>
              </div>

              {/* Real Live On-Chain Balance Card */}
              <div className="my-2.5 p-3 rounded-xl bg-gradient-to-br from-emerald-500/10 via-zinc-900/90 to-zinc-950 border border-emerald-500/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
                <div className="flex items-center justify-between text-[10.5px] text-zinc-400 mb-1" style={{ direction: 'ltr' }}>
                  <span className="font-medium text-zinc-300">Polygon USDT Vault</span>
                  <button
                    type="button"
                    disabled={isRefreshingBalance}
                    onClick={async () => {
                      sounds.playClick();
                      setIsRefreshingBalance(true);
                      try {
                        await refreshBalance();
                      } finally {
                        setTimeout(() => setIsRefreshingBalance(false), 500);
                      }
                    }}
                    className="text-emerald-400 hover:text-emerald-300 flex items-center gap-1 text-[10px] font-mono cursor-pointer disabled:opacity-50 transition-colors px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20"
                    title="Refresh live on-chain balance"
                  >
                    <RefreshCw className={cn('w-3 h-3', isRefreshingBalance && 'animate-spin')} />
                    <span>{isRefreshingBalance ? 'Syncing...' : 'Sync'}</span>
                  </button>
                </div>
                <div className="flex items-baseline justify-between mt-1.5" style={{ direction: 'ltr' }}>
                  <div>
                    <div className="text-xl font-bold font-mono text-emerald-300 tracking-tight" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                      ${wallet.balance.toFixed(2)}{' '}
                      <span className="text-xs font-sans text-emerald-400 font-semibold">USDT</span>
                    </div>
                    <div className="text-[10px] font-medium text-zinc-400 mt-0.5 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_4px_#34d399]"></span>
                      <span className="font-mono text-[9.5px]">Smart Escrow Settlement</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      sounds.playClick();
                      setShowDepositModal(true);
                    }}
                    className="text-[10.5px] font-semibold text-emerald-300 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 px-2.5 py-1.5 rounded-lg transition-all cursor-pointer flex items-center gap-1 active:scale-95 shadow-[0_2px_8px_rgba(52,211,153,0.2)]"
                  >
                    <ArrowDownLeft className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Deposit / QR</span>
                  </button>
                </div>
              </div>

              {/* Quick Duel Stats Row */}
              <div className="mb-2.5 grid grid-cols-3 gap-1.5 p-2 rounded-xl bg-white/[0.02] border border-white/[0.06] text-center" style={{ direction: 'ltr' }}>
                <div className="p-1">
                  <div className="text-[9.5px] text-zinc-400 font-medium">Duels</div>
                  <div className="text-xs font-bold font-mono text-zinc-100">{stats.totalMatches || 0}</div>
                </div>
                <div className="p-1 border-x border-white/[0.06]">
                  <div className="text-[9.5px] text-zinc-400 font-medium">Win Rate</div>
                  <div className="text-xs font-bold font-mono text-emerald-400">
                    {stats.totalMatches ? Math.round(((stats.wins || 0) / stats.totalMatches) * 100) : 0}%
                  </div>
                </div>
                <div className="p-1">
                  <div className="text-[9.5px] text-zinc-400 font-medium">Best Reflex</div>
                  <div className="text-xs font-bold font-mono text-sky-400">
                    {stats.bestReactionMs ? `${stats.bestReactionMs}ms` : '--'}
                  </div>
                </div>
              </div>

              {/* Wallet Address Box */}
              <div className="mb-2.5 p-2 rounded-xl bg-zinc-900/90 border border-white/[0.08] flex items-center justify-between gap-2" style={{ direction: 'ltr' }}>
                <div className="min-w-0 flex-1">
                  <div className="text-[9.5px] text-zinc-400 uppercase tracking-wider font-mono font-medium">
                    Wallet Address
                  </div>
                  <div
                    data-wallet-address="true"
                    className="text-[11px] font-mono text-zinc-200 truncate mt-0.5 font-medium"
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '11px',
                      direction: 'ltr',
                    }}
                    title={fullAddr}
                  >
                    {fullAddr}
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={handleCopyAddress}
                    className={cn(
                      'p-1.5 rounded-lg border transition-all cursor-pointer flex items-center gap-1 text-[10px] font-mono',
                      copiedAddr
                        ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                        : 'bg-white/[0.04] hover:bg-white/[0.08] border-white/[0.08] text-zinc-300 hover:text-white'
                    )}
                    title="Copy full address"
                  >
                    {copiedAddr ? (
                      <>
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        <span>Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3 text-zinc-400" />
                        <span>Copy</span>
                      </>
                    )}
                  </button>

                  <a
                    href={`https://polygonscan.com/address/${fullAddr}`}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-colors cursor-pointer"
                    title="View on Polygonscan"
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </div>

              {/* Disconnect Session */}
              <div className="pt-2 border-t border-white/[0.06]">
                <button
                  type="button"
                  onClick={() => {
                    sounds.playClick();
                    disconnectWallet();
                    setDropdownOpen(false);
                  }}
                  className="w-full py-2 px-2.5 rounded-xl text-xs text-rose-400 hover:text-rose-300 bg-rose-500/5 hover:bg-rose-500/15 border border-rose-500/20 transition-all flex items-center justify-center gap-1.5 cursor-pointer font-medium active:scale-[0.99]"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Disconnect Session</span>
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Receive / Deposit USDT On-Chain Modal */}
        {showDepositModal &&
          mounted &&
          createPortal(
            <div className="fixed inset-0 z-[999999] flex items-center justify-center p-4">
              <div
                className="fixed inset-0 bg-black/80 backdrop-blur-sm"
                onClick={() => setShowDepositModal(false)}
              />
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="relative z-10 w-full max-w-sm rounded-2xl bg-zinc-950 border border-emerald-500/30 p-5 shadow-2xl space-y-4 text-left"
                dir="ltr"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                      <ArrowDownLeft className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-white">Receive Polygon USDT</h4>
                      <p className="text-[11px] text-zinc-400">Non-Custodial Polygon (137) Deposit</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setShowDepositModal(false)}
                    className="text-zinc-500 hover:text-white p-1 rounded-lg"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* QR Code */}
                <div className="flex flex-col items-center justify-center p-3 bg-white rounded-xl shadow-inner mx-auto w-fit">
                  <QRCodeSVG value={fullAddr} size={150} />
                </div>

                {/* Address Box */}
                <div>
                  <label className="text-[11px] text-zinc-400 block mb-1">Your Polygon Address</label>
                  <div className="p-2.5 rounded-xl bg-zinc-900 border border-white/[0.08] flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-zinc-200 truncate select-all">{fullAddr}</span>
                    <button
                      type="button"
                      onClick={handleCopyAddress}
                      className={cn(
                        'px-2 py-1 rounded-lg border transition-all text-[10.5px] font-mono shrink-0 flex items-center gap-1',
                        copiedAddr
                          ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                          : 'bg-white/[0.06] hover:bg-white/[0.12] border-white/[0.08] text-white'
                      )}
                    >
                      {copiedAddr ? <CheckCircle2 className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>{copiedAddr ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5 text-[11px] text-zinc-400 bg-white/[0.02] p-2.5 rounded-xl border border-white/[0.05]">
                  <div className="flex justify-between">
                    <span>Network</span>
                    <span className="text-emerald-400 font-semibold font-mono">Polygon Mainnet (Chain 137)</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Token</span>
                    <span className="text-zinc-200 font-mono">USDT (Tether USD)</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Token Contract</span>
                    <span className="text-zinc-400 font-mono text-[10px]">0xc213...91bc</span>
                  </div>
                </div>

                <form onSubmit={handleConfirmDeposit} className="space-y-2">
                  <button
                    type="submit"
                    disabled={isRefreshingBalance}
                    className="w-full py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-black font-bold text-xs tracking-tight transition-all cursor-pointer shadow-lg shadow-emerald-500/20 active:scale-95 flex items-center justify-center gap-1.5"
                  >
                    <RefreshCw className={cn('w-3.5 h-3.5', isRefreshingBalance && 'animate-spin')} />
                    <span>{isRefreshingBalance ? 'Checking RPC...' : 'Check / Refresh On-Chain Balance'}</span>
                  </button>

                  {depositStatusMsg && (
                    <div className="p-2 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold text-center">
                      {depositStatusMsg}
                    </div>
                  )}
                </form>
              </motion.div>
            </div>,
            document.body
          )}
      </div>
    );
  }

  // -------------------------------------------------------------
  // DISCONNECTED STATE: Clean Light-Grey Trigger Button & OpenSea-Style Modal
  // -------------------------------------------------------------
  return (
    <>
      {/* Light-Grey Icon Button matching original aesthetic */}
      <button
        type="button"
        onClick={() => {
          sounds.playClick();
          setErrorMessage(null);
          setIsOpen(true);
        }}
        className="linear-card rounded-full px-3 h-8 flex items-center justify-center gap-1.5 text-xs font-medium text-zinc-300 hover:text-white hover:bg-zinc-800 active:scale-95 transition-all cursor-pointer shadow-sm whitespace-nowrap shrink-0 leading-none"
      >
        <Wallet className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
        <span className="whitespace-nowrap leading-none">
          {compact ? t('connectWalletShort') : t('connectWallet')}
        </span>
      </button>

      {/* OpenSea-Style Mobile-First Modal */}
      {mounted &&
        createPortal(
          <AnimatePresence>
            {isOpen && (
              <div className="fixed inset-0 z-[999999] flex items-end sm:items-center justify-center sm:p-4">
                {/* Backdrop */}
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="fixed inset-0 bg-black/80 backdrop-blur-md"
                  onClick={handleCloseModal}
                />

                {/* Modal Window: Bottom Sheet on Mobile, Centered Card on Desktop */}
                <motion.div
                  initial={{ y: '100%', opacity: 0.5 }}
                  animate={{ y: 0, opacity: 1 }}
                  exit={{ y: '100%', opacity: 0 }}
                  transition={{ type: 'spring', damping: 30, stiffness: 350 }}
                  className={cn(
                    'relative z-10 w-full bg-[#121214] border border-white/[0.1] shadow-[0_24px_64px_rgba(0,0,0,0.85)] overflow-hidden text-left',
                    'rounded-t-3xl sm:rounded-3xl sm:max-w-md p-5 sm:p-6 max-h-[90vh] flex flex-col'
                  )}
                  style={{ direction: 'ltr' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Mobile Drag Indicator */}
                  <div className="w-10 h-1 bg-white/20 rounded-full mx-auto mb-3 sm:hidden shrink-0" />

                  {/* Standard Web3 Modal Header */}
                  <div className="flex items-start justify-between pb-3.5 border-b border-white/[0.08] shrink-0">
                    <div>
                      <h3 className="text-base sm:text-lg font-bold text-white tracking-tight">
                        {activeHandoff || connectingWalletId
                          ? `Connecting ${activeHandoff?.walletName || connectingWalletId}`
                          : 'Connect a Wallet'}
                      </h3>
                      <p className="text-xs text-zinc-400 mt-0.5 leading-normal">
                        {activeHandoff || connectingWalletId
                          ? 'Approve in your wallet app, then return to this browser'
                          : 'Tap a wallet. It opens only to approve the session — this site stays in Safari/Chrome.'}
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={handleCloseModal}
                      className="text-zinc-400 hover:text-white p-1.5 rounded-full hover:bg-white/[0.08] transition-colors cursor-pointer shrink-0 -mr-1"
                      aria-label="Close"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Dedicated Tab Banner (Helps mobile testing bypass iframe restrictions) */}
                  {isIframeOrSandboxed() && (
                    <div className="mt-3 p-3 rounded-2xl bg-gradient-to-r from-sky-500/15 via-blue-500/10 to-transparent border border-sky-500/30 flex items-center justify-between gap-3 text-left shrink-0">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 text-xs font-bold text-sky-300">
                          <Sparkles className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                          <span>1-Tap Mobile Testing</span>
                        </div>
                        <p className="text-[11px] text-zinc-300 mt-0.5 leading-snug">
                          Open in a dedicated fullscreen tab for direct 1-click mobile wallet app launch.
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          sounds.playClick();
                          window.open(window.location.href, '_blank', 'noopener,noreferrer');
                        }}
                        className="px-3 py-1.5 rounded-xl bg-sky-500 hover:bg-sky-400 active:scale-95 text-zinc-950 font-bold text-xs shrink-0 flex items-center gap-1.5 shadow-md shadow-sky-500/20 cursor-pointer transition-all"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        <span>Dedicated Tab</span>
                      </button>
                    </div>
                  )}

                  {/* Error Notification Banner */}
                  {errorMessage && (
                    <motion.div
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="mt-3.5 p-3 rounded-2xl bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs flex items-start gap-2.5 shrink-0"
                    >
                      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <span className="text-xs leading-relaxed block">{errorMessage}</span>
                        <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                          <button
                            type="button"
                            onClick={() => {
                              window.open(window.location.href, '_blank');
                            }}
                            className="px-2.5 py-1.5 rounded-lg bg-white/[0.08] hover:bg-white/[0.14] text-white text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 active:scale-95"
                          >
                            <ExternalLink className="w-3 h-3" />
                            <span>Open in Dedicated Tab</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setErrorMessage(null)}
                            className="px-2.5 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-[11px] transition-colors cursor-pointer"
                          >
                            Dismiss
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  <div className="flex flex-col flex-1 min-h-0">
                      {isWalletInAppBrowser() && (
                        <div className="mt-3 p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between gap-2.5 shrink-0 text-left">
                          <div className="min-w-0">
                            <div className="text-xs font-bold text-white flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                              <span>In-App Mobile Web3 Detected</span>
                            </div>
                            <p className="text-[11px] text-zinc-300 mt-0.5 truncate">
                              Tap to connect directly with your wallet app.
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleConnectWalletItem('MetaMask', 'In-App Wallet')}
                            className="px-3 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 text-xs font-bold shrink-0 shadow cursor-pointer transition-colors"
                          >
                            Connect Now
                          </button>
                        </div>
                      )}

                      {/* Active Mobile / Deep Link Handoff Card */}
                      {activeHandoff && (
                        <motion.div
                          initial={{ opacity: 0, scale: 0.97 }}
                          animate={{ opacity: 1, scale: 1 }}
                          className="mt-3 p-4 rounded-2xl bg-zinc-900/95 border border-emerald-500/40 space-y-3.5 shrink-0 shadow-2xl text-left"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-center gap-3 min-w-0">
                              <div className="w-10 h-10 rounded-xl bg-white/[0.06] border border-white/10 flex items-center justify-center p-2 shrink-0">
                                {OPENSEA_WALLETS.find((w) => w.id === activeHandoff.walletId)?.logo || (
                                  <Wallet className="w-5 h-5 text-emerald-400" />
                                )}
                              </div>
                              <div className="min-w-0">
                                <h4 className="text-sm font-bold text-white truncate">
                                  Authorize with {activeHandoff.walletName}
                                </h4>
                                <p className="text-[11px] text-zinc-400 mt-0.5">
                                  {activeHandoff.uri
                                    ? 'Session ready. Tap below to approve in your wallet app:'
                                    : 'Generating secure encrypted session code...'}
                                </p>
                              </div>
                            </div>

                            <button
                              type="button"
                              onClick={() => {
                                sounds.playClick();
                                cancelPendingConnect();
                                setActiveHandoff(null);
                                setConnectingWalletId(null);
                              }}
                              className="p-1 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 transition-colors shrink-0"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>

                          {/* PRIMARY ACTION: DIRECT SESSION APPROVAL IN NATIVE WALLET */}
                          <div className="space-y-2">
                            {activeHandoff.uri ? (
                              <a
                                href={getNativeSchemeUri(activeHandoff.walletId, activeHandoff.uri)}
                                onClick={() => {
                                  sounds.playClick();
                                  openWalletConnectInNativeApp(activeHandoff.walletId, activeHandoff.uri);
                                }}
                                className="w-full py-3 px-4 rounded-xl font-black text-xs sm:text-sm flex items-center justify-center gap-2 transition-all cursor-pointer shadow-lg bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-400 hover:brightness-110 text-zinc-950 shadow-emerald-500/25 active:scale-[0.98]"
                              >
                                <ShieldCheck className="w-4 h-4 text-zinc-950 shrink-0" />
                                <span>Open {activeHandoff.walletName} to Approve</span>
                              </a>
                            ) : (
                              <button
                                type="button"
                                disabled
                                className="w-full py-3 px-4 rounded-xl font-black text-xs sm:text-sm flex items-center justify-center gap-2 bg-white/5 text-zinc-500 border border-white/5 cursor-not-allowed"
                              >
                                <Loader2 className="w-4 h-4 animate-spin text-zinc-400 shrink-0" />
                                <span>Preparing session...</span>
                              </button>
                            )}

                            <p className="text-[10px] text-zinc-400 leading-tight text-center">
                              {activeHandoff.walletName} opens only to approve. After you confirm, iOS returns you to this Safari/Chrome tab — already connected.
                            </p>
                          </div>

                          {/* SECONDARY CONTROLS: Universal Link, Copy Code, QR Code, Paste Address */}
                          <div className="pt-2 border-t border-white/[0.08] space-y-2">
                            <div className="grid grid-cols-2 gap-2">
                              {/* Universal Web Link fallback */}
                              <button
                                type="button"
                                disabled={!activeHandoff.uri}
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  sounds.playClick();
                                  if (!activeHandoff.uri) return;
                                  openWalletConnectInNativeApp(activeHandoff.walletId, activeHandoff.uri);
                                }}
                                className={cn(
                                  'py-2 px-3 rounded-xl font-bold text-xs flex items-center justify-center gap-1.5 transition-all cursor-pointer',
                                  activeHandoff.uri
                                    ? 'bg-white/10 hover:bg-white/15 text-white border border-white/20 active:scale-95'
                                    : 'bg-white/5 text-zinc-500 border border-white/5 cursor-not-allowed'
                                )}
                              >
                                <ExternalLink className="w-3.5 h-3.5" />
                                <span>Open again</span>
                              </button>

                              {/* Copy Code button */}
                              <button
                                type="button"
                                disabled={!activeHandoff.uri}
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  sounds.playClick();
                                  if (!activeHandoff.uri) return;
                                  navigator.clipboard.writeText(activeHandoff.uri);
                                  setCopiedUri(true);
                                  setTimeout(() => setCopiedUri(false), 2500);
                                }}
                                className={cn(
                                  'py-2 px-3 rounded-xl font-bold text-xs flex items-center justify-center gap-1.5 transition-all cursor-pointer',
                                  activeHandoff.uri
                                    ? 'bg-sky-500/15 hover:bg-sky-500/25 text-sky-400 border border-sky-500/30 active:scale-95'
                                    : 'bg-white/5 text-zinc-500 border border-white/5 cursor-not-allowed'
                                )}
                              >
                                {copiedUri ? (
                                  <>
                                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                                    <span className="text-emerald-400">Copied!</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="w-3.5 h-3.5" />
                                    <span>Copy Code</span>
                                  </>
                                )}
                              </button>
                            </div>

                            {copiedUri && (
                              <p className="text-[10px] text-emerald-400 leading-tight bg-emerald-500/10 p-2 rounded-lg border border-emerald-500/20">
                                Pairing code copied! In {activeHandoff.walletName}: Settings &gt; WalletConnect &gt; Paste link to approve.
                              </p>
                            )}

                            <div className="pt-1 flex items-center justify-center text-[11px]">
                              <button
                                type="button"
                                disabled={!activeHandoff.uri}
                                onClick={() => {
                                  sounds.playClick();
                                  setShowHandoffQr(!showHandoffQr);
                                }}
                                className={cn(
                                  'text-zinc-400 hover:text-white transition-colors flex items-center gap-1 cursor-pointer font-medium',
                                  !activeHandoff.uri && 'opacity-40 pointer-events-none'
                                )}
                              >
                                <QrCode className="w-3.5 h-3.5 text-teal-400" />
                                <span>{showHandoffQr ? 'Hide QR Code' : 'Scan QR Code'}</span>
                              </button>
                            </div>

                            {showHandoffQr && activeHandoff.uri && (
                              <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                className="pt-2 flex flex-col items-center text-center"
                              >
                                <div className="p-3 bg-white rounded-xl shadow-inner inline-block">
                                  <QRCodeSVG value={activeHandoff.uri} size={160} />
                                </div>
                                <span className="text-[10.5px] text-zinc-400 mt-1.5">
                                  Scan using {activeHandoff.walletName} camera on another device
                                </span>
                              </motion.div>
                            )}
                          </div>
                        </motion.div>
                      )}

                      {/* OpenSea-Style Wallet List */}
                      <div className="mt-3.5 space-y-2 overflow-y-auto pr-0.5 flex-1 max-h-[50vh] sm:max-h-[380px] no-scrollbar">
                        {/* EIP-6963 Discovered Injected Wallets */}
                        {eip6963Providers
                          .filter(
                            (p) =>
                              !OPENSEA_WALLETS.some((w) =>
                                w.name.toLowerCase().includes(p.info.name.toLowerCase())
                              )
                          )
                          .map((p) => {
                            const isConnecting = connectingWalletId === p.info.rdns;
                            return (
                              <button
                                key={p.info.rdns}
                                type="button"
                                disabled={Boolean(connectingWalletId)}
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  setConnectingWalletId(p.info.rdns);
                                  setErrorMessage(null);
                                  sounds.playClick();
                                  connectEIP6963(p)
                                    .then(() => {
                                      sounds.playWin();
                                      setIsOpen(false);
                                    })
                                    .catch((err) => {
                                      sounds.playLoss();
                                      setErrorMessage(err?.message || 'Connection failed');
                                    })
                                    .finally(() => setConnectingWalletId(null));
                                }}
                                className={cn(
                                  'w-full h-14 px-4 rounded-2xl bg-white/[0.03] hover:bg-white/[0.08] active:scale-[0.99]',
                                  'border border-white/[0.07] hover:border-white/[0.18] transition-all flex items-center justify-between cursor-pointer group'
                                )}
                              >
                                <div className="flex items-center gap-3.5 min-w-0">
                                  <div className="w-9 h-9 rounded-xl bg-white/[0.05] border border-white/[0.08] flex items-center justify-center p-1.5 shrink-0">
                                    <img
                                      src={p.info.icon}
                                      alt={p.info.name}
                                      className="w-full h-full object-contain"
                                    />
                                  </div>
                                  <div className="text-left min-w-0">
                                    <span className="text-sm font-semibold text-white group-hover:text-white block truncate">
                                      {p.info.name}
                                    </span>
                                    <span className="text-[11px] text-emerald-400 font-medium block">
                                      Detected Extension
                                    </span>
                                  </div>
                                </div>

                                <div className="flex items-center gap-2 shrink-0">
                                  <span className="text-[10.5px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                    Installed
                                  </span>
                                  {isConnecting ? (
                                    <Loader2 className="w-4 h-4 text-zinc-300 animate-spin" />
                                  ) : (
                                    <ChevronRight className="w-4 h-4 text-zinc-500 group-hover:text-white transition-transform group-hover:translate-x-0.5" />
                                  )}
                                </div>
                              </button>
                            );
                          })}

                        {/* Standard OpenSea Wallets */}
                        {OPENSEA_WALLETS.map((item) => {
                          const isConnecting = connectingWalletId === item.id;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              disabled={Boolean(connectingWalletId)}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleConnectWalletItem(item.id, item.name);
                              }}
                              className={cn(
                                'w-full h-14 px-4 rounded-2xl bg-white/[0.03] hover:bg-white/[0.08] active:scale-[0.99]',
                                'border border-white/[0.07] hover:border-white/[0.18] transition-all flex items-center justify-between cursor-pointer group',
                                connectingWalletId && !isConnecting && 'opacity-40 pointer-events-none'
                              )}
                            >
                              <div className="flex items-center gap-3.5 min-w-0">
                                {/* Official Logo Container */}
                                <div className="w-9 h-9 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center p-1.5 shrink-0 group-hover:border-white/[0.14] transition-colors">
                                  {item.logo}
                                </div>

                                {/* Wallet Info */}
                                <div className="text-left min-w-0">
                                  <div className="text-sm font-semibold text-zinc-100 group-hover:text-white truncate">
                                    {item.name}
                                  </div>
                                  {item.subtitle && (
                                    <div className="text-[11px] text-zinc-400 truncate">
                                      {item.subtitle}
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Right Side Badges & Status */}
                              <div className="flex items-center gap-2 shrink-0">
                                {item.badge && (
                                  <span
                                    className={cn(
                                      'text-[10.5px] font-medium px-2 py-0.5 rounded-full border',
                                      item.badgeType === 'popular' &&
                                        'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
                                      item.badgeType === 'instant' &&
                                        'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
                                      item.badgeType === 'detected' &&
                                        'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                                    )}
                                  >
                                    {item.badge}
                                  </span>
                                )}

                                {isConnecting ? (
                                  <Loader2 className="w-4 h-4 text-zinc-300 animate-spin" />
                                ) : (
                                  <ChevronRight className="w-4 h-4 text-zinc-500 group-hover:text-white transition-transform group-hover:translate-x-0.5" />
                                )}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                  {/* OpenSea-Style Accordion Help */}
                  <AnimatePresence>
                    {showHelp && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mt-3 p-3 rounded-2xl bg-zinc-900/90 border border-white/[0.08] text-xs text-zinc-300 space-y-2 overflow-hidden shrink-0"
                      >
                        <div className="font-semibold text-white flex items-center gap-1.5">
                          <HelpCircle className="w-3.5 h-3.5 text-sky-400" />
                          <span>What is a Web3 wallet?</span>
                        </div>
                        <p className="text-[11.5px] text-zinc-400 leading-relaxed">
                          A wallet lets you log in, authorize duels, and hold your tournament USDT
                          directly on Polygon without custody by third parties.
                        </p>
                        <p className="text-[11.5px] text-zinc-400 leading-relaxed">
                          On mobile, simply tap your wallet (MetaMask, Trust Wallet, etc.) to issue permission and connect directly.
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* OpenSea-Style Footer */}
                  <div className="mt-4 pt-3.5 border-t border-white/[0.06] text-center space-y-1.5 shrink-0">
                    <p className="text-[11px] text-zinc-500 leading-relaxed max-w-xs mx-auto">
                      By connecting your wallet, you agree to the Terms of Service & Privacy Policy.
                    </p>
                    <div className="flex items-center justify-center gap-1 text-[11px] text-zinc-400">
                      <span>Need help?</span>
                      <button
                        type="button"
                        onClick={() => setShowHelp(!showHelp)}
                        className="text-sky-400 hover:text-sky-300 hover:underline font-medium cursor-pointer"
                      >
                        {showHelp ? 'Hide guide' : 'Learn about wallets'}
                      </button>
                    </div>
                  </div>
                </motion.div>
              </div>
            )}
          </AnimatePresence>,
          document.body
        )}
    </>
  );
};
