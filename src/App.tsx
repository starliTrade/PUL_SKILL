import React, { Suspense, lazy, useState, useEffect } from 'react';
import type { LegalTab } from './pages/LegalPage';
import { EligibilityGate } from './components/EligibilityGate';
import { ErrorBoundary } from './components/ErrorBoundary';
import { BottomNav, TabType } from './components/BottomNav';

// Audit-#5 item 10 — route-level code splitting. Every page is lazy-loaded,
// so Rollup emits one chunk per route and the initial bundle no longer pulls
// the whole web3/game stack (ethers, confetti, motion) for a landing-page
// visit. The game route — the heaviest — is only fetched when actually played.
const HomePage = lazy(() => import('./pages/HomePage').then((m) => ({ default: m.HomePage })));
const LobbyPage = lazy(() => import('./pages/LobbyPage').then((m) => ({ default: m.LobbyPage })));
const ReactionGamePage = lazy(() => import('./pages/ReactionGamePage').then((m) => ({ default: m.ReactionGamePage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((m) => ({ default: m.ProfilePage })));
const LegalPage = lazy(() => import('./pages/LegalPage').then((m) => ({ default: m.LegalPage })));

const RouteFallback = () => (
  <div className="min-h-[60vh] flex items-center justify-center">
    <div className="flex flex-col items-center gap-3 text-slate-400">
      <div className="h-8 w-8 rounded-full border-2 border-sky-500/30 border-t-sky-400 animate-spin" />
      <span className="text-xs tracking-widest uppercase">Loading…</span>
    </div>
  </div>
);

const KNOWN_PATHS = ['/', '/lobby', '/dashboard', '/profile', '/game/reaction', '/legal'];

export default function App() {
  const [currentPath, setCurrentPath] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const pathname = window.location.pathname;
      if (KNOWN_PATHS.includes(pathname)) {
        return pathname;
      }
    }
    return '/';
  });

  const [legalTab, setLegalTab] = useState<LegalTab>('tos');

  const [activeOpponent, setActiveOpponent] = useState<string | undefined>(undefined);
  const [activeStake, setActiveStake] = useState<number>(1);

  useEffect(() => {
    const handlePopState = () => {
      const pathname = window.location.pathname;
      if (KNOWN_PATHS.includes(pathname)) {
        setCurrentPath(pathname);
      } else {
        setCurrentPath('/');
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (path: string, opponent?: string, stake?: number, legalTab?: LegalTab) => {
    if (path === '/legal' && legalTab) setLegalTab(legalTab);
    if (opponent !== undefined) {
      setActiveOpponent(opponent);
    }
    if (stake !== undefined) {
      setActiveStake(stake);
    }
    setCurrentPath(path);
    window.scrollTo({ top: 0, behavior: 'instant' });
    try {
      window.history.pushState({}, '', path);
    } catch {
      // ignore
    }
  };

  const isGameRoute = currentPath === '/game/reaction';

  return (
    <ErrorBoundary>
    <div className="min-h-screen bg-[#07080a] text-slate-100 flex flex-col font-sans selection:bg-sky-500/30 selection:text-white">
      {/* Route Views (lazy-loaded chunks per route) */}
      <Suspense fallback={<RouteFallback />}>
        {currentPath === '/' && <HomePage onNavigate={navigate} />}
        {currentPath === '/lobby' && (
          <LobbyPage
            onNavigate={navigate}
            onStartDuelWithOpponent={(opp, stake) => {
              setActiveOpponent(opp);
              if (stake) setActiveStake(stake);
            }}
          />
        )}
        {currentPath === '/game/reaction' && (
          <ReactionGamePage
            onNavigate={navigate}
            opponentName={activeOpponent}
            stakeAmount={activeStake}
          />
        )}
        {currentPath === '/dashboard' && <DashboardPage onNavigate={navigate} />}
        {currentPath === '/profile' && <ProfilePage onNavigate={navigate} />}
        {currentPath === '/legal' && <LegalPage onNavigate={navigate} initialTab={legalTab} />}
      </Suspense>

      {/* P2.3 — first-visit 18+ / jurisdiction eligibility gate */}
      <EligibilityGate />

      {/* Floating Bottom Navigation (hidden during active reaction game) */}
      {!isGameRoute && (
        <BottomNav
          currentPath={currentPath as TabType}
          onNavigate={(path) => navigate(path)}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
