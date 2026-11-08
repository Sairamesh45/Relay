import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/api/client';

export interface CircuitStatus {
  target: string;
  provider: string;
  state: 'closed' | 'open' | 'half_open';
  failureCount: number;
  threshold: number;
  openDurationSeconds: number;
  probeInFlight: boolean;
  description: string;
}

export interface CircuitBreakersProps {
  initialCircuits?: CircuitStatus[];
}

export const CircuitBreakers: React.FC<CircuitBreakersProps> = ({
  initialCircuits,
}) => {
  const [circuits, setCircuits] = useState<CircuitStatus[]>(
    initialCircuits || []
  );

  useEffect(() => {
    if (initialCircuits) return;
    let mounted = true;

    async function loadCircuits() {
      try {
        const [credsRes, healthRes] = await Promise.allSettled([
          api.providers.credentials(),
          api.reliability.credentialsHealth(),
        ]);

        const creds =
          credsRes.status === 'fulfilled' && Array.isArray(credsRes.value)
            ? credsRes.value
            : [];
        const healthList =
          healthRes.status === 'fulfilled' && Array.isArray(healthRes.value)
            ? healthRes.value
            : [];

        if (mounted && creds.length > 0) {
          const providerNames: Record<string, string> = {
            google: 'Google Gemini',
            gemini: 'Google Gemini',
            groq: 'Groq',
            cerebras: 'Cerebras',
            openrouter: 'OpenRouter',
          };

          const mapped: CircuitStatus[] = creds.map((c: any) => {
            const h = healthList.find(
              (item: any) => item.credential_id === c.id
            );
            const prov =
              providerNames[c.provider?.toLowerCase()] || c.provider;
            const target = `${prov} (${c.key_nickname || 'Default'})`;

            let state: 'closed' | 'open' | 'half_open' = 'closed';
            const failureCount = h?.consecutive_failures || 0;
            let probeInFlight = false;
            let description =
              'Normal traffic flowing with zero consecutive upstream errors.';

            if (h?.is_cooling_down) {
              state = 'open';
              description = `Cooldown active (${
                h.last_error_category || 'Rate limited'
              }). Fast-failing upstream requests.`;
            } else if (
              h?.health_status === 'degraded' ||
              h?.health_status === 'half_open'
            ) {
              state = 'half_open';
              probeInFlight = true;
              description =
                'Cooldown expired. 1 recovery probe currently testing upstream response.';
            } else if (failureCount > 0) {
              description = `${failureCount} transient timeout/error observed in rolling window; below trip threshold.`;
            }

            return {
              target,
              provider: prov,
              state,
              failureCount,
              threshold: 5,
              openDurationSeconds: 30,
              probeInFlight,
              description,
            };
          });

          setCircuits(mapped);
        }
      } catch {
        // Handled cleanly
      }
    }

    loadCircuits();
    return () => {
      mounted = false;
    };
  }, [initialCircuits]);

  return (
    <GlassCard className="p-6" data-testid="circuit-breakers-card">
      <div className="flex justify-between items-center mb-1 flex-wrap gap-2">
        <h2 className="font-display text-[22px] font-normal text-ink">
          Circuit Breakers
        </h2>
        <span className="text-[12.5px] text-mute">
          PostgreSQL-backed fault isolation
        </span>
      </div>
      <p className="text-[13px] text-mute mb-5">
        Prevents cascading outages by fast-failing broken providers and testing recovery safely.
      </p>

      {circuits.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 max-app:grid-cols-1">
          {circuits.map((cb) => {
            const isClosed = cb.state === 'closed';
            const isOpen = cb.state === 'open';

            return (
              <div
                key={cb.target}
                className="p-4 rounded-[16px] bg-white/40 border border-line"
                data-testid={`circuit-card-${cb.state}`}
              >
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <b className="font-semibold text-ink text-[14px]">
                      {cb.target}
                    </b>
                    <div className="text-[12.5px] text-mute mt-0.5">
                      {cb.provider}
                    </div>
                  </div>

                  <Pill
                    variant={
                      isClosed ? 'default' : isOpen ? 'warning' : 'neutral'
                    }
                  >
                    {isClosed
                      ? 'Closed (Normal)'
                      : isOpen
                      ? 'Open (Tripped)'
                      : 'Half-Open (Testing)'}
                  </Pill>
                </div>

                <p className="text-[12.5px] text-mute my-2 leading-relaxed">
                  {cb.description}
                </p>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-line text-[12px] text-mute">
                  <div>
                    Failures:{' '}
                    <b className="text-ink font-mono">
                      {cb.failureCount} / {cb.threshold}
                    </b>
                  </div>
                  <div>
                    Probe in flight:{' '}
                    <b className="text-ink font-mono">
                      {cb.probeInFlight ? 'Active (1 max)' : 'None'}
                    </b>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="p-8 text-center text-mute text-[13px] rounded-[16px] bg-ink/5 border border-line">
          No circuit breakers active. Connect provider credentials to monitor circuit health and failure isolation.
        </div>
      )}
    </GlassCard>
  );
};
