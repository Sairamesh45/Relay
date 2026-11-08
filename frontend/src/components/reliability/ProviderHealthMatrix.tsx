import React, { useState, useEffect, useCallback } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Pill } from '@/components/ui/Pill';
import { DonutRing } from '@/components/ui/DonutRing';
import { Sparkline } from '@/components/ui/Sparkline';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/context/ToastContext';
import { api } from '@/api/client';

export interface ProviderHealthItem {
  id: string;
  name: string;
  isCoolingDown: boolean;
  cooldownSeconds: number;
  modelsCount: number;
  connectedKeys: string;
  medianLatency: string;
  latencyHistory: number[];
  quotaPercent: number;
  confirmedByProvider: boolean;
}

export interface ProviderHealthMatrixProps {
  initialProviders?: ProviderHealthItem[];
}

const DEFAULT_CHANNELS: ProviderHealthItem[] = [
  {
    id: 'google',
    name: 'Google Gemini',
    isCoolingDown: false,
    cooldownSeconds: 0,
    modelsCount: 0,
    connectedKeys: '0 keys',
    medianLatency: '0 ms',
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    quotaPercent: 0,
    confirmedByProvider: false,
  },
  {
    id: 'groq',
    name: 'Groq',
    isCoolingDown: false,
    cooldownSeconds: 0,
    modelsCount: 0,
    connectedKeys: '0 keys',
    medianLatency: '0 ms',
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    quotaPercent: 0,
    confirmedByProvider: false,
  },
  {
    id: 'cerebras',
    name: 'Cerebras',
    isCoolingDown: false,
    cooldownSeconds: 0,
    modelsCount: 0,
    connectedKeys: '0 keys',
    medianLatency: '0 ms',
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    quotaPercent: 0,
    confirmedByProvider: false,
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    isCoolingDown: false,
    cooldownSeconds: 0,
    modelsCount: 0,
    connectedKeys: '0 keys',
    medianLatency: '0 ms',
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    quotaPercent: 0,
    confirmedByProvider: false,
  },
];

export const ProviderHealthMatrix: React.FC<ProviderHealthMatrixProps> = ({
  initialProviders,
}) => {
  const [providers, setProviders] = useState<ProviderHealthItem[]>(
    initialProviders || DEFAULT_CHANNELS
  );
  const { showToast } = useToast();

  const loadLiveHealth = useCallback(async () => {
    if (initialProviders) return;

    try {
      const [credsRes, healthRes, modelsRes, usageRes] = await Promise.allSettled([
        api.providers.credentials(),
        api.reliability.credentialsHealth(),
        api.models.list(),
        api.usage.summary(),
      ]);

      const creds =
        credsRes.status === 'fulfilled' && Array.isArray(credsRes.value)
          ? credsRes.value
          : [];
      const healthList =
        healthRes.status === 'fulfilled' && Array.isArray(healthRes.value)
          ? healthRes.value
          : [];
      const models =
        modelsRes.status === 'fulfilled' && Array.isArray(modelsRes.value?.models)
          ? modelsRes.value.models
          : [];
      const usage =
        usageRes.status === 'fulfilled' ? usageRes.value : null;

      setProviders((prev) =>
        prev.map((p) => {
          const matchingCreds = creds.filter(
            (c: any) => c.provider?.toLowerCase() === p.id.toLowerCase()
          );

          if (matchingCreds.length === 0) {
            return {
              ...p,
              connectedKeys: '0 keys',
              modelsCount: 0,
              isCoolingDown: false,
              cooldownSeconds: 0,
              medianLatency: '0 ms',
              quotaPercent: 0,
            };
          }

          const primaryCred = matchingCreds[0];
          const healthRecord = healthList.find(
            (h: any) => h.credential_id === primaryCred.id
          );

          const matchingModels = models.filter(
            (m: any) => m.provider?.toLowerCase() === p.id.toLowerCase()
          );

          let isCooling = false;
          let remainingSeconds = 0;
          let confirmed = false;

          if (healthRecord?.is_cooling_down && healthRecord.cooldown_until) {
            const until = new Date(healthRecord.cooldown_until).getTime();
            const now = Date.now();
            if (until > now) {
              isCooling = true;
              remainingSeconds = Math.ceil((until - now) / 1000);
              confirmed = healthRecord.last_error_category === 'RATE_LIMIT_429';
            }
          }

          const pUsage = usage?.by_provider?.[p.id];
          const medianLat = pUsage?.average_latency_ms
            ? `${Math.round(pUsage.average_latency_ms)} ms`
            : p.medianLatency !== '0 ms'
            ? p.medianLatency
            : '0 ms';

          return {
            ...p,
            connectedKeys: `${matchingCreds.length} ${
              matchingCreds.length === 1 ? 'key' : 'keys'
            }`,
            modelsCount: matchingModels.length,
            isCoolingDown: isCooling,
            cooldownSeconds: remainingSeconds,
            confirmedByProvider: confirmed,
            medianLatency: medianLat,
          };
        })
      );
    } catch {
      // Graceful error fallback
    }
  }, [initialProviders]);

  useEffect(() => {
    loadLiveHealth();
  }, [loadLiveHealth]);

  // 1-second countdown for cooling down providers
  useEffect(() => {
    const timer = setInterval(() => {
      setProviders((prev) =>
        prev.map((p) => {
          if (p.isCoolingDown && p.cooldownSeconds > 0) {
            const nextSec = p.cooldownSeconds - 1;
            if (nextSec === 0) {
              showToast(`${p.name} cooldown expired. Returned to routing pool.`);
              return { ...p, isCoolingDown: false, cooldownSeconds: 0 };
            }
            return { ...p, cooldownSeconds: nextSec };
          }
          return p;
        })
      );
    }, 1000);

    return () => clearInterval(timer);
  }, [showToast]);

  const handleCheckNow = async (providerId: string, providerName: string) => {
    try {
      const creds = await api.providers.credentials();
      const match = creds?.find((c: any) => c.provider?.toLowerCase() === providerId.toLowerCase());
      if (match?.id) {
        await api.providers.validate(match.id);
        showToast(`Connection to ${providerName} verified and healthy`);
        loadLiveHealth();
      } else {
        showToast(`No credential configured for ${providerName}`);
      }
    } catch (err: any) {
      showToast(err.message || `Health check failed for ${providerName}`);
    }
  };

  return (
    <div className="grid grid-cols-2 gap-4 max-app:grid-cols-1" data-testid="provider-health-matrix">
      {providers.map((p) => (
        <GlassCard key={p.id} className="p-6 relative">
          {/* Card Top: Provider name & Health pill */}
          <div className="flex justify-between items-center mb-4">
            <h2 className="font-display text-[22px] font-normal text-ink">
              {p.name}
            </h2>
            <Pill variant={p.isCoolingDown ? 'warning' : 'default'}>
              {p.isCoolingDown ? 'Cooling down' : 'Healthy'}
            </Pill>
          </div>

          {/* Middle: Quota Donut Ring & Latency Sparkline */}
          <div className="flex items-center gap-5 my-4">
            <DonutRing percent={p.quotaPercent} size={76} strokeWidth={3} />
            <div className="flex-1">
              <div className="text-[13px] text-mute mb-1">Latency, last hour</div>
              <Sparkline
                data={p.latencyHistory}
                color={p.isCoolingDown ? '#FF66E0' : '#5B3DFF'}
              />
            </div>
          </div>

          {/* Stats Row */}
          <div className="flex gap-6 text-[13px] text-mute my-3">
            <span>
              <b className="block text-ink font-display text-[20px] font-normal">
                {p.modelsCount}
              </b>
              models
            </span>
            <span>
              <b className="block text-ink font-display text-[20px] font-normal">
                {p.medianLatency}
              </b>
              median
            </span>
            <span>
              <b className="block text-ink font-display text-[20px] font-normal">
                {p.connectedKeys}
              </b>
              connected
            </span>
          </div>

          {/* Cooldown Alert Banner */}
          {p.isCoolingDown && (
            <div
              className="mt-4 p-3.5 rounded-[14px] bg-pink/16 text-[13px] text-ink"
              data-testid={`cooldown-banner-${p.id}`}
            >
              <b className="font-semibold text-ink">Rate limited.</b> Back in{' '}
              <span className="font-mono font-semibold text-pink">
                {p.cooldownSeconds}s
              </span>
              .{' '}
              {p.confirmedByProvider
                ? 'Reset time confirmed by the provider.'
                : 'Reset time estimated via exponential backoff.'}
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex gap-2 mt-4 pt-3 border-t border-line">
            <Button
              variant="line"
              onClick={() => handleCheckNow(p.id, p.name)}
            >
              Check now
            </Button>
            <Button
              variant="line"
              onClick={() => showToast(`Opened key settings for ${p.name}`)}
            >
              Manage keys
            </Button>
          </div>
        </GlassCard>
      ))}
    </div>
  );
};
