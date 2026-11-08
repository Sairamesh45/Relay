import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/api/client';

export interface QuotaEntry {
  provider: string;
  scope: string;
  resource: string;
  limitFormatted: string;
  remainingFormatted: string;
  percentUsed: number;
  resetInfo: string;
  confidence: 'Confirmed' | 'Estimated';
}

export interface QuotaGaugesProps {
  initialQuotas?: QuotaEntry[];
}

export const QuotaGauges: React.FC<QuotaGaugesProps> = ({ initialQuotas }) => {
  const [quotas, setQuotas] = useState<QuotaEntry[]>(initialQuotas || []);

  useEffect(() => {
    if (initialQuotas) return;
    let mounted = true;

    async function loadQuotas() {
      try {
        const res = await api.reliability.quotas();
        if (mounted && res?.items && Array.isArray(res.items)) {
          const providerNames: Record<string, string> = {
            google: 'Google Gemini',
            gemini: 'Google Gemini',
            groq: 'Groq',
            cerebras: 'Cerebras',
            openrouter: 'OpenRouter',
          };

          const mapped: QuotaEntry[] = res.items.map((q: any) => {
            const prov = providerNames[q.provider?.toLowerCase()] || q.provider;
            const scope = q.quota_scope
              ? `${q.quota_scope}${q.model_id ? ` (${q.model_id})` : ''}`
              : 'Default';
            const resource =
              q.resource_type === 'requests'
                ? 'Request Rate (RPM)'
                : q.resource_type === 'tokens'
                ? 'Token Rate (TPM)'
                : q.resource_type;
            const limitFormatted = q.limit
              ? `${q.limit.toLocaleString()} ${
                  q.resource_type === 'requests' ? 'RPM' : ''
                }`.trim()
              : 'Unlimited';
            const remainingFormatted =
              q.remaining != null
                ? `${q.remaining.toLocaleString()} remaining`
                : '—';
            const percentUsed =
              q.limit && q.remaining != null
                ? Math.max(
                    0,
                    Math.min(
                      100,
                      Math.round(((q.limit - q.remaining) / q.limit) * 100)
                    )
                  )
                : 0;
            const resetInfo = q.retry_after
              ? `Resets in ${q.retry_after}s`
              : q.reset_at
              ? `Resets at ${new Date(q.reset_at).toLocaleTimeString()}`
              : 'Resets in rolling window';
            const confidence = (
              q.confidence?.toLowerCase() === 'confirmed'
                ? 'Confirmed'
                : 'Estimated'
            ) as 'Confirmed' | 'Estimated';

            return {
              provider: prov,
              scope,
              resource,
              limitFormatted,
              remainingFormatted,
              percentUsed,
              resetInfo,
              confidence,
            };
          });

          setQuotas(mapped);
        }
      } catch {
        // Handled cleanly
      }
    }

    loadQuotas();
    return () => {
      mounted = false;
    };
  }, [initialQuotas]);

  return (
    <GlassCard className="p-6" data-testid="quota-gauges-card">
      <div className="flex justify-between items-center mb-1 flex-wrap gap-2">
        <h2 className="font-display text-[22px] font-normal text-ink">
          Quota & Rate Limit Utilization
        </h2>
        <span className="text-[12.5px] text-mute">
          Observed from provider rate-limit response headers
        </span>
      </div>
      <p className="text-[13px] text-mute mb-5">
        Real-time tracking of requests per minute, daily limits, and token budgets.
      </p>

      {quotas.length > 0 ? (
        <div className="space-y-4">
          {quotas.map((q, idx) => (
            <div
              key={`${q.provider}-${q.resource}-${idx}`}
              className="p-3.5 rounded-[16px] bg-white/40 border border-line"
            >
              <div className="flex justify-between items-start mb-2 flex-wrap gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <b className="text-[14px] font-semibold text-ink">
                      {q.provider}
                    </b>
                    <span className="text-mute text-[12.5px]">· {q.scope}</span>
                  </div>
                  <div className="text-[12.5px] text-mute mt-0.5">{q.resource}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-mono text-mute">
                    {q.remainingFormatted} / {q.limitFormatted}
                  </span>
                  <Pill variant={q.confidence === 'Confirmed' ? 'default' : 'neutral'}>
                    {q.confidence}
                  </Pill>
                </div>
              </div>

              {/* Quota Progress Bar */}
              <div className="flex items-center gap-3">
                <div className="flex-1 h-[6px] rounded-[9px] bg-ink/8 overflow-hidden">
                  <div
                    className={`h-full rounded-[9px] transition-all duration-300 ${
                      q.percentUsed > 80
                        ? 'bg-gradient-to-r from-pink to-[#FFB3EE]'
                        : 'bg-gradient-to-r from-violet to-pink'
                    }`}
                    style={{ width: `${q.percentUsed}%` }}
                  />
                </div>
                <span className="text-[12.5px] font-mono font-medium text-ink w-9 text-right">
                  {q.percentUsed}%
                </span>
              </div>

              <div className="text-[11.5px] text-mute/80 mt-1.5 flex justify-between">
                <span>{q.resetInfo}</span>
                <span>
                  {q.percentUsed > 80 ? 'Approaching capacity' : 'Healthy margin'}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-8 text-center text-mute text-[13px] rounded-[16px] bg-ink/5 border border-line">
          No quota observations recorded yet. Provider rate-limit and header data will appear automatically as gateway requests are executed.
        </div>
      )}
    </GlassCard>
  );
};
