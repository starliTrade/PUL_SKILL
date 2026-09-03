import React from 'react';
import { PulsarHeroVisualizer } from './PulsarHeroVisualizer';
import { cn } from '../lib/utils';

interface HeroOrbProps {
  className?: string;
  onStartBattle?: () => void;
}

export const HeroOrb: React.FC<HeroOrbProps> = ({ className, onStartBattle }) => {
  return (
    <div
      className={cn('relative flex items-center justify-center w-full h-full', className)}
    >
      <PulsarHeroVisualizer className="w-full h-full" onStartBattle={onStartBattle} />
    </div>
  );
};

