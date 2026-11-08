import React, { useMemo } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Pill } from '@/components/ui/Pill';

export interface ProviderShare {
  name: string;
  sharePercent: number;
}

export interface ModelCostRow {
  provider: string;
  model: string;
  requests: number;
  inputTokens: string;
  outputTokens: string;
  cost: string;
  isFreeTier: boolean;
}

export interface CostBreakdownProps {
  byProvider?: Record<
    string,
    {
      total_requests: number;
      total_tokens: number;
      input_tokens: number;
      output_tokens: number;
    }
  >;
  byModel?: Record<string, number>;
  initialShares?: ProviderShare[];
  initialRows?: ModelCostRow[];
  savingsFormatted?: string;
}

export const CostBreakdown: React.FC<CostBreakdownProps> = ({
  byProvider,
  byModel,
  initialShares,
  initialRows,
  savingsFormatted,
}) => {
  const shares: ProviderShare[] = useMemo(() => {
    if (initialShares) return initialShares;
    if (!byProvider || Object.keys(byProvider).length === 0) return [];

    const total = Object.values(byProvider).reduce(
      (acc, p) => acc + (p.total_requests || 0),
      0
    );

    const providerDisplayNames: Record<string, string> = {
      google: 'Google Gemini',
      gemini: 'Google Gemini',
      groq: 'Groq',
      cerebras: 'Cerebras',
      openrouter: 'OpenRouter',
    };

    return Object.entries(byProvider).map(([key, val]) => ({
      name: providerDisplayNames[key.toLowerCase()] || key,
      sharePercent:
        total > 0 ? Math.round(((val.total_requests || 0) / total) * 100) : 0,
    }));
  }, [byProvider, initialShares]);

  const rows: ModelCostRow[] = useMemo(() => {
    if (initialRows) return initialRows;
    if (!byModel || Object.keys(byModel).length === 0) return [];

    return Object.entries(byModel).map(([modelName, reqCount]) => {
      let prov = 'Gateway';
      const mLower = modelName.toLowerCase();
      if (mLower.includes('gemini')) prov = 'Google Gemini';
      else if (mLower.includes('groq') || mLower.includes('llama')) prov = 'Groq';
      else if (mLower.includes('cerebras')) prov = 'Cerebras';
      else if (mLower.includes('qwen') || mLower.includes('openrouter'))
        prov = 'OpenRouter';

      return {
        provider: prov,
        model: modelName,
        requests: reqCount,
        inputTokens: '—',
        outputTokens: '—',
        cost: '$0.00',
        isFreeTier: true,
      };
    });
  }, [byModel, initialRows]);

  const savingsText =
    savingsFormatted ||
    (rows.length > 0 || shares.length > 0 ? '$0.00 saved' : '$0.00 saved');

  return (
    <div className="space-y-4" data-testid="cost-breakdown-section">
      {/* Share by Provider Card */}
      <GlassCard className="p-6">
        <h2 className="font-display text-[22px] font-normal text-ink mb-1">
          Share by Provider
        </h2>
        <p className="text-[13px] text-mute mb-5">
          Request routing proportion across active providers.
        </p>

        {shares.length > 0 ? (
          <div className="space-y-3.5">
            {shares.map((prov) => (
              <div key={prov.name} className="flex items-center gap-3 text-[14px]">
                <span className="w-28 text-ink font-medium truncate">
                  {prov.name}
                </span>
                <div className="flex-1 h-[6px] rounded-[9px] bg-ink/8 overflow-hidden">
                  <div
                    className="h-full rounded-[9px] bg-gradient-to-r from-violet to-pink transition-all duration-500"
                    style={{ width: `${prov.sharePercent}%` }}
                  />
                </div>
                <span className="w-10 text-right text-mute font-mono text-[13px]">
                  {prov.sharePercent}%
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-6 text-center text-mute text-[13px] rounded-[16px] bg-ink/5 border border-line">
            No provider traffic recorded yet. Make a request via the gateway to see routing distribution.
          </div>
        )}
      </GlassCard>

      {/* Model & Cost Table */}
      <GlassCard className="p-6">
        <div className="flex justify-between items-center mb-4 flex-wrap gap-2">
          <div>
            <h2 className="font-display text-[22px] font-normal text-ink">
              Cost & Token Breakdown
            </h2>
            <p className="text-[13px] text-mute mt-0.5">
              Accounting summary per connected provider and model.
            </p>
          </div>
          <div className="text-right">
            <span className="text-[12.5px] text-mute">Estimated Savings</span>
            <b className="block font-display text-[20px] text-violet font-semibold">
              {savingsText}
            </b>
          </div>
        </div>

        {rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[14px]">
              <thead>
                <tr className="border-b border-line text-mute text-[13px] font-medium">
                  <th className="pb-3 pr-3 font-medium">Provider</th>
                  <th className="pb-3 pr-3 font-medium">Model</th>
                  <th className="pb-3 pr-3 font-medium">Requests</th>
                  <th className="pb-3 pr-3 font-medium">Input Tokens</th>
                  <th className="pb-3 pr-3 font-medium">Output Tokens</th>
                  <th className="pb-3 pr-3 font-medium">Cost</th>
                  <th className="pb-3 font-medium text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row, idx) => (
                  <tr
                    key={`${row.provider}-${row.model}-${idx}`}
                    className="hover:bg-white/40"
                  >
                    <td className="py-3.5 pr-3 text-ink font-medium">
                      {row.provider}
                    </td>
                    <td className="py-3.5 pr-3 text-ink">{row.model}</td>
                    <td className="py-3.5 pr-3 text-mute font-mono text-[13px]">
                      {row.requests.toLocaleString()}
                    </td>
                    <td className="py-3.5 pr-3 text-mute font-mono text-[13px]">
                      {row.inputTokens}
                    </td>
                    <td className="py-3.5 pr-3 text-mute font-mono text-[13px]">
                      {row.outputTokens}
                    </td>
                    <td className="py-3.5 pr-3 font-mono font-medium text-ink">
                      {row.cost}
                    </td>
                    <td className="py-3.5 text-right">
                      <Pill variant={row.isFreeTier ? 'default' : 'neutral'}>
                        {row.isFreeTier ? 'Free Tier' : 'Paid Tier'}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-mute text-[13px] rounded-[16px] bg-ink/5 border border-line">
            No model or cost breakdown data recorded yet.
          </div>
        )}
      </GlassCard>
    </div>
  );
};
