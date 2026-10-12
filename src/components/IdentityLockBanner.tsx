import React from 'react';

/**
 * H15b — surfaces the identity lock.
 *
 * H15 refuses an account or network switch while a ranked match is live and
 * records why on `identityLockedReason`. Nothing rendered it, so the player's
 * switch was refused and the app said nothing — the same "your action was
 * silently ignored" experience the lock was meant to remove.
 *
 * Placeholder: renders nothing. This is the current behaviour, and the red
 * baseline for H15b.
 */
export const IdentityLockBanner: React.FC = () => null;
