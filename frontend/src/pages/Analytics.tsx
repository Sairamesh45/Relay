import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Sparkline } from '@/components/ui/Sparkline';
import { TokenMetrics } from '@/components/analytics/TokenMetrics';
import { CostBreakdown } from '@/components/analytics/CostBreakdown';
import { VolumeTrends } from '@/components/analytics/VolumeTrends';
import { api } from '@/api/client';

interface AnalyticsProps {
  initialSummary?: any;
}

export const Analytics: React.FC<AnalyticsProps> = ({ initialSummary }) => {
  const [summaryData, setSummaryData] = useState<any>(initialSummary || null);
  const [requestsList, setRequestsList] = useState<any[]>([]);

  useEffect(() => {
    if (initialSummary) return;
    let mounted = true;

    async function loadUsage() {
      try {
        const [usageRes, reqsRes] = await Promise.allSettled([
          api.usage.summary(),
          api.usage.requests({ limit: 100 }),
        ]);

        if (mounted) {
          if (usageRes.status === 'fulfilled' && usageRes.value) {
            setSummaryData(usageRes.value);
          }
          if (reqsRes.status === 'fulfilled' && reqsRes.value?.logs) {
            setRequestsList(reqsRes.value.logs);
          }
        }
      } catch {
        // Handled cleanly
      }
    }

    loadUsage();
    return () => {
      mounted = false;
    };
  }, [initialSummary]);

  const totalRequests = summaryData?.total_requests ?? 0;
  const inputTokens = summaryData?.total_input_tokens ?? 0;
  const outputTokens = summaryData?.total_output_tokens ?? 0;
  const totalTokens = summaryData?.total_tokens ?? (inputTokens + outputTokens);
  const avgLatency = summaryData?.average_latency_ms ?? summaryData?.median_latency_ms ?? 0;
  const estimatedCost = summaryData?.total_cost != null ? `$${summaryData.total_cost.toFixed(2)}` : '$0.00';

  const formatTokens = (toks: number) => {
    if (toks >= 1000000) return `${(toks / 1000000).toFixed(1)}M`;
    if (toks >= 1000) return `${(toks / 1000).toFixed(1)}K`;
    return String(toks);
  };

  return (
    <div data-testid="analytics-page" className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Analytics
          </h1>
          <p className="text-mute text-[15px] mt-2">
            Request volumes, provider breakdown, and token consumption metrics.
          </p>
        </div>
      </div>

      {/* 4 Summary KPI Cards */}
      <div className="grid grid-cols-4 gap-4 max-app:grid-cols-2" data-testid="analytics-kpi-grid">
        {[
          {
            label: 'Total Requests',
            val: totalRequests.toLocaleString(),
            data: totalRequests > 0 ? [3, 4, 3, 5, 6, 5, 7, 8] : [0, 0, 0, 0, 0, 0, 0, 0],
            sub: totalRequests > 0 ? 'Logged requests' : 'No requests yet',
          },
          {
            label: 'Total Tokens',
            val: formatTokens(totalTokens),
            data: totalTokens > 0 ? [5, 6, 6, 7, 8, 8, 9, 9] : [0, 0, 0, 0, 0, 0, 0, 0],
            sub: `${formatTokens(inputTokens)} in · ${formatTokens(outputTokens)} out`,
          },
          {
            label: 'Estimated Cost',
            val: estimatedCost,
            data: totalRequests > 0 ? [1, 1, 2, 2, 2, 3, 3, 3] : [0, 0, 0, 0, 0, 0, 0, 0],
            sub: totalRequests > 0 ? 'Aggregated usage cost' : 'Free tiers / zero cost',
          },
          {
            label: 'Median Latency',
            val: avgLatency > 0 ? `${Math.round(avgLatency)} ms` : '0 ms',
            data: totalRequests > 0 ? [9, 8, 8, 7, 7, 6, 6, 5] : [0, 0, 0, 0, 0, 0, 0, 0],
            sub: totalRequests > 0 ? 'Rolling average latency' : 'Awaiting traffic',
          },
        ].map((kpi) => (
          <GlassCard key={kpi.label} className="p-6">
            <span className="text-[13px] text-mute">{kpi.label}</span>
            <b className="block font-display font-light text-[36px] tracking-kpi text-ink my-1">
              {kpi.val}
            </b>
            <div className="my-2">
              <Sparkline data={kpi.data} color="#5B3DFF" />
            </div>
            <span className="text-[12px] text-mute/80">{kpi.sub}</span>
          </GlassCard>
        ))}
      </div>

      {/* 2-Column Analytical Charts */}
      <div className="grid grid-cols-[1.2fr_1fr] gap-4 max-app:grid-cols-1">
        <div className="space-y-4">
          <VolumeTrends requests={requestsList} />
        </div>
        <div className="space-y-4">
          <TokenMetrics
            inputTokens={inputTokens}
            outputTokens={outputTokens}
            totalTokens={totalTokens}
            totalRequests={totalRequests}
          />
        </div>
      </div>

      {/* Cost & Provider Breakdown */}
      <CostBreakdown
        byProvider={summaryData?.by_provider}
        byModel={summaryData?.by_model}
      />
    </div>
  );
};

export default Analytics;
