import React from 'react';
import { cn } from '../lib/utils';
import { PulsarDynamicAvatar } from './PulsarDynamicAvatar';

interface UserAvatarProps {
  address?: string;
  playerId?: string;
  level?: number;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
  showBadge?: boolean;
}

export const UserAvatar: React.FC<UserAvatarProps> = ({
  level = 1,
  size = 'md',
  className,
  showBadge = true,
}) => {
  return (
    <PulsarDynamicAvatar
      level={level}
      size={size}
      className={className}
      showBadge={showBadge}
    />
  );
};
