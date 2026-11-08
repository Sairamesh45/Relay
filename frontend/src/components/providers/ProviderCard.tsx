import React from 'react';
import { GlassCard, Pill, DonutRing, Sparkline, Button } from '@/components/ui';

export interface ProviderData {
  id: string;
  name: string;
  providerKey: 'google' | 'groq' | 'openrouter';
  isHealthy: boolean;
  modelCount: number;
  medianLatency: string;
  connectedKeys: string;
  quotaPercent: number;
  latencyHistory: number[];
  isCoolingDown?: boolean;
  cooldownSeconds?: number;
  cooldownConfirmed?: boolean;
  credentialId?: string;
}

interface ProviderCardProps {
  provider: ProviderData;
  onCheckNow?: (provider: ProviderData) => Promise<void> | void;
  onManageKeys?: (provider: ProviderData) => void;
  isChecking?: boolean;
}

export const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  onCheckNow,
  onManageKeys,
  isChecking = false,
}) => {
  const isCoolingDown = provider.isCoolingDown && (provider.cooldownSeconds ?? 0) > 0;
  const sparklineColor = isCoolingDown ? '#FF66E0' : '#5B3DFF';

  return (
    <GlassCard className="relative p-6 flex flex-col justify-between">
      <div>
        {/* Top Header */}
        <div className="flex justify-between items-center mb-1">
          <h2 className="font-display font-normal text-[22px] leading-appHeadline text-ink">
            {provider.name}
          </h2>
          {isCoolingDown ? (
            <Pill variant="warning">Cooling down</Pill>
          ) : provider.isHealthy ? (
            <Pill variant="default">Healthy</Pill>
          ) : (
            <Pill variant="neutral">Not connected</Pill>
          )}
        </div>

        {/* Middle Stats Section */}
        <div className="flex items-center gap-5 my-[18px]">
          <DonutRing percent={provider.quotaPercent} size={76} />
          <div className="flex-1 min-w-0">
            <div className="text-[13px] text-mute mb-1">Latency, last hour</div>
            <Sparkline data={provider.latencyHistory} color={sparklineColor} height={30} />
          </div>
        </div>

        {/* Stats Row */}
        <div className="flex gap-[22px] text-[13px] text-mute mb-4">
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {provider.modelCount}
            </b>
            models
          </span>
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {provider.medianLatency}
            </b>
            median
          </span>
          <span>
            <b className="block text-ink font-display font-normal text-[20px] leading-tight">
              {provider.connectedKeys}
            </b>
            connected
          </span>
        </div>

        {/* Live Cooldown Alert Card */}
        {isCoolingDown && (
          <div
            role="alert"
            className="mt-4 p-3 px-[14px] rounded-[14px] bg-[rgba(255,102,224,0.16)] text-[13px] text-ink leading-relaxed border border-[rgba(255,102,224,0.3)] animate-in"
          >
            <b>Rate limited.</b> Back in{' '}
            <span data-cd className="font-semibold text-pink-dark">
              {provider.cooldownSeconds}s
            </span>
            .{provider.cooldownConfirmed ? ' Reset time confirmed by the provider.' : ' Estimated backoff.'}
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="flex gap-2 mt-4 pt-2">
        <Button
          variant="line"
          onClick={() => onCheckNow?.(provider)}
          disabled={isChecking}
          className="text-[13px] px-4 py-2"
        >
          {isChecking ? 'Checking…' : 'Check now'}
        </Button>
        <Button
          variant="line"
          onClick={() => onManageKeys?.(provider)}
          className="text-[13px] px-4 py-2"
        >
          Manage keys
        </Button>
      </div>
    </GlassCard>
  );
};
