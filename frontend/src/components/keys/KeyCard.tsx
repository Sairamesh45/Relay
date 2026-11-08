import React from 'react';
import { GlassCard, Pill, Button } from '@/components/ui';
import { VirtualAPIKey } from '@/types';

interface KeyCardProps {
  apiKey: VirtualAPIKey;
  onEdit?: (key: VirtualAPIKey) => void;
  onEditPolicy?: (key: VirtualAPIKey) => void;
  onRevoke: (key: VirtualAPIKey) => void;
  isRevoking?: boolean;
}

export const KeyCard: React.FC<KeyCardProps> = ({
  apiKey,
  onEdit,
  onEditPolicy,
  onRevoke,
  isRevoking = false,
}) => {
  const usagePercent = Math.min(100, Math.max(0, apiKey.dailyUsagePercent ?? 0));
  const handleEditClick = onEditPolicy || onEdit;

  return (
    <GlassCard className="relative p-6 flex flex-col justify-between">
      <div>
        {/* Top Header */}
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-display font-normal text-[22px] leading-appHeadline text-ink">
            {apiKey.name}
          </h2>
          <Pill variant={apiKey.isActive ? 'default' : 'neutral'}>
            {apiKey.isActive ? 'Active' : 'Revoked'}
          </Pill>
        </div>

        {/* Masked Key Display */}
        <div className="font-mono text-[13px] text-mute my-2 tracking-wide">
          {apiKey.keyPrefix}
        </div>

        {/* Stats Row */}
        <div className="flex gap-[22px] text-[13px] text-mute my-4">
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {apiKey.strategy}
            </b>
            strategy
          </span>
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {apiKey.modelAccess}
            </b>
            access
          </span>
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {apiKey.expiresAt}
            </b>
            expires
          </span>
        </div>

        {/* Daily Request Limit Progress Bar */}
        <div className="mt-4">
          <div className="flex justify-between text-[13px] text-mute mb-[6px]">
            <span>Daily limit used</span>
            <span className="font-medium text-ink">{usagePercent}%</span>
          </div>
          <div className="h-[6px] rounded-[9px] bg-[rgba(26,21,48,0.08)] overflow-hidden">
            <i
              className="block h-full rounded-[9px] bg-gradient-to-r from-violet to-pink transition-all duration-300"
              style={{ width: `${usagePercent}%` }}
              role="progressbar"
              aria-valuenow={usagePercent}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>
      </div>

      {/* Footer Actions */}
      <div className="flex gap-2 mt-5 pt-1">
        <Button
          variant="line"
          onClick={() => handleEditClick?.(apiKey)}
          disabled={!apiKey.isActive}
          className="text-[13px] px-4 py-2"
        >
          Edit
        </Button>
        <Button
          variant="line"
          onClick={() => onRevoke(apiKey)}
          disabled={isRevoking || !apiKey.isActive}
          className="text-[13px] px-4 py-2 text-mute hover:text-ink hover:border-pink"
        >
          {isRevoking ? 'Revoking…' : 'Revoke'}
        </Button>
      </div>
    </GlassCard>
  );
};
