import React from 'react';
import { Lock } from 'lucide-react';

import { usePulsarStore } from '../store/usePulsarStore';

/**
 * H15b — surfaces the identity lock.
 *
 * H15 refuses an account or network switch while a ranked match is live and
 * records why on `identityLockedReason`. Nothing rendered it, so the player's
 * switch was refused and the app said nothing — the same "your action was
 * silently ignored" experience the lock was meant to remove.
 *
 * Renders nothing when there is no lock: a permanent banner would be noise.
 */
export const IdentityLockBanner: React.FC = () => {
  const { identityLockedReason } = usePulsarStore();
  if (!identityLockedReason) return null;

  return (
    <div
      data-testid="pulsar-identity-lock"
      role="status"
      className="w-full px-4 py-2 flex items-center gap-2 bg-amber-500/10 border-b border-amber-400/20 text-amber-200"
    >
      <Lock className="w-3.5 h-3.5 shrink-0" />
      <p className="text-[11px] leading-snug">{identityLockedReason}</p>
    </div>
  );
};
