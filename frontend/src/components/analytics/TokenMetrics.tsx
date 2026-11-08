import React from 'react';
import { GlassCard } from '@/components/ui/GlassCard';

export interface TokenMetricsProps {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  totalRequests?: number;
  cacheEfficiency?: number;
}

export const TokenMetrics: React.FC<TokenMetricsProps> = ({
  inputTokens = 0,
  outputTokens = 0,
  totalTokens = 0,
  totalRequests = 0,
  cacheEfficiency,
}) => {
  const calculatedTotal = totalTokens > 0 ? totalTokens : inputTokens + outputTokens;
  const inputPercent = calculatedTotal > 0 ? Math.round((inputTokens / calculatedTotal) * 100) : 0;
  const outputPercent = calculatedTotal > 0 ? 100 - inputPercent : 0;

  const formatTokens = (toks: number) => {
    if (toks >= 1000000) return `${(toks / 1000000).toFixed(1)}M`;
    if (toks >= 1000) return `${(toks / 1000).toFixed(1)}K`;
    return toks.toLocaleString();
  };

  const avgTokensPerRequest =
    totalRequests > 0
      ? Math.round(calculatedTotal / totalRequests).toLocaleString()
      : calculatedTotal > 0
      ? calculatedTotal.toLocaleString()
      : '0';

  const cacheEfficiencyDisplay =
    cacheEfficiency != null
      ? `${cacheEfficiency.toFixed(1)}%`
      : '0.0%';

  return (
    <GlassCard className="p-6" data-testid="token-metrics-card">
      <h2 className="font-display text-[22px] font-normal text-ink mb-1">
        Token Consumption
      </h2>
      <p className="text-[13px] text-mute mb-5">
        Breakdown of prompt input and generation output tokens.
      </p>

      {/* Dual Stacked Progress Bar */}
      <div className="h-3 rounded-full bg-ink/8 flex overflow-hidden p-0.5 mb-3">
        {calculatedTotal > 0 ? (
          <>
            <div
              className="h-full rounded-l-full bg-gradient-to-r from-violet to-[#7A5CFF] transition-all duration-500"
              style={{ width: `${inputPercent}%` }}
              title={`Input tokens: ${formatTokens(inputTokens)} (${inputPercent}%)`}
            />
            <div
              className="h-full rounded-r-full bg-gradient-to-r from-[#FFB3EE] to-pink transition-all duration-500"
              style={{ width: `${outputPercent}%` }}
              title={`Output tokens: ${formatTokens(outputTokens)} (${outputPercent}%)`}
            />
          </>
        ) : (
          <div className="h-full w-full bg-transparent" />
        )}
      </div>

      <div className="flex justify-between items-center text-[12.5px] text-mute mb-6">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-violet" />
          <span>
            Input: <b className="text-ink">{formatTokens(inputTokens)}</b> ({inputPercent}%)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-pink" />
          <span>
            Output: <b className="text-ink">{formatTokens(outputTokens)}</b> ({outputPercent}%)
          </span>
        </div>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 gap-4 pt-4 border-t border-line">
        <div>
          <span className="text-[12.5px] text-mute">Avg. tokens / request</span>
          <b className="block font-display text-[24px] text-ink mt-0.5">
            {avgTokensPerRequest}
          </b>
        </div>
        <div>
          <span className="text-[12.5px] text-mute">Cache hit efficiency</span>
          <b className="block font-display text-[24px] text-ink mt-0.5">
            {cacheEfficiencyDisplay}
          </b>
        </div>
      </div>
    </GlassCard>
  );
};
