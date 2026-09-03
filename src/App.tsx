import React, { useState, useEffect } from 'react';
import { HomePage } from './pages/HomePage';
import { LobbyPage } from './pages/LobbyPage';
import { ReactionGamePage } from './pages/ReactionGamePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilePage } from './pages/ProfilePage';
import { BottomNav, TabType } from './components/BottomNav';

export default function App() {
  const [currentPath, setCurrentPath] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const pathname = window.location.pathname;
      if (['/lobby', '/dashboard', '/profile', '/game/reaction'].includes(pathname)) {
        return pathname;
      }
    }
    return '/';
  });

  const [activeOpponent, setActiveOpponent] = useState<string | undefined>(undefined);
  const [activeStake, setActiveStake] = useState<number>(1);

  useEffect(() => {
    const handlePopState = () => {
      const pathname = window.location.pathname;
      if (['/', '/lobby', '/dashboard', '/profile', '/game/reaction'].includes(pathname)) {
        setCurrentPath(pathname);
      } else {
        setCurrentPath('/');
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (path: string, opponent?: string, stake?: number) => {
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
