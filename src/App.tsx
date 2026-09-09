import React, { useState, useEffect } from 'react';
import { HomePage } from './pages/HomePage';
import { LobbyPage } from './pages/LobbyPage';
import { ReactionGamePage } from './pages/ReactionGamePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilePage } from './pages/ProfilePage';
import { LegalPage, type LegalTab } from './pages/LegalPage';
import { EligibilityGate } from './components/EligibilityGate';
import { BottomNav, TabType } from './components/BottomNav';

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
    <div className="min-h-screen bg-[#07080a] text-slate-100 flex flex-col font-sans selection:bg-sky-500/30 selection:text-white">
      {/* Route Views */}
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
  );
}
