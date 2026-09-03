import React from 'react';
import { motion } from 'motion/react';
import { House, Gamepad2, LayoutDashboard, User } from 'lucide-react';
import { sounds } from '../lib/sound';
import { cn } from '../lib/utils';
import { useLanguage } from '../i18n/LanguageContext';

export type TabType = '/' | '/lobby' | '/dashboard' | '/profile';

interface BottomNavProps {
  currentPath: string;
  onNavigate: (path: TabType) => void;
}

export const BottomNav: React.FC<BottomNavProps> = ({ currentPath, onNavigate }) => {
  const { t } = useLanguage();

  const NAV_ITEMS = [
    { href: '/' as TabType, label: t('navHome'), icon: House },
    { href: '/lobby' as TabType, label: t('navArena'), icon: Gamepad2 },
    { href: '/dashboard' as TabType, label: t('navDashboard'), icon: LayoutDashboard },
    { href: '/profile' as TabType, label: t('navProfile'), icon: User },
  ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 safe-bottom pointer-events-none navbar-strict-ltr" dir="ltr" style={{ direction: 'ltr' }}>
      <div className="mx-auto max-w-md px-3 pb-3 pt-1.5 pointer-events-auto">
        <div className="bg-zinc-950/65 border border-white/[0.08] rounded-2xl flex items-center justify-around p-1 shadow-[0_8px_32px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-2xl">
          {NAV_ITEMS.map((item) => {
            const isActive = currentPath === item.href;
            const Icon = item.icon;

            return (
              <button
                key={item.href}
                onClick={() => {
                  sounds.playClick();
                  onNavigate(item.href);
                }}
                className={cn(
                  'relative flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-xl transition-all cursor-pointer select-none',
                  isActive ? 'text-white font-medium' : 'text-zinc-500 hover:text-zinc-300'
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="nav-pill"
                    className="absolute inset-0 rounded-xl bg-white/[0.06]"
                    transition={{ type: 'spring', stiffness: 450, damping: 32 }}
                  />
                )}
                <Icon className={cn("w-4 h-4 relative z-10 transition-colors shrink-0", isActive ? "text-white" : "text-zinc-500")} />
                <span className="text-[11px] font-medium relative z-10 whitespace-nowrap">{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
};
