import React from 'react';
import { GlassCard } from '@/components/ui';

export interface ModelRoute {
  provider: string;
  isAvailable: boolean;
  latencyMs?: number;
}

export interface ModelRowData {
  id: string;
  name: string;
  routes: ModelRoute[];
  contextWindow: string;
  capabilities: string[];
}

interface UnifiedModelTableProps {
  models: ModelRowData[];
  isLoading?: boolean;
}

export const UnifiedModelTable: React.FC<UnifiedModelTableProps> = ({
  models,
  isLoading = false,
}) => {
  return (
    <GlassCard className="p-6 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="text-left font-medium text-mute text-[13px] pb-3 pr-3">Model</th>
            <th className="text-left font-medium text-mute text-[13px] pb-3 pr-3">Routes</th>
            <th className="text-left font-medium text-mute text-[13px] pb-3 pr-3">Context</th>
            <th className="text-left font-medium text-mute text-[13px] pb-3 pr-3">Capabilities</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={4} className="py-8 text-center text-mute">
                Loading models…
              </td>
            </tr>
          ) : models.length === 0 ? (
            <tr>
              <td colSpan={4} className="py-8 text-center text-mute">
                No matching models found.
              </td>
            </tr>
          ) : (
            models.map((model) => (
              <tr key={model.id} className="border-t border-line transition-colors hover:bg-white/40">
                <td className="py-[14px] pr-3 align-middle">
                  <b className="font-semibold text-ink text-[14.5px]">{model.name}</b>
                </td>
                <td className="py-[14px] pr-3 align-middle">
                  <div className="flex flex-wrap gap-2">
                    {model.routes.map((route, idx) => (
                      <span
                        key={`${route.provider}-${idx}`}
                        className="inline-flex items-center gap-[6px] text-[13px] text-ink"
                        title={route.isAvailable ? 'Route active and eligible' : 'Route cooling down / paused'}
                      >
                        <i
                          className={`inline-block w-[7px] h-[7px] rounded-full shrink-0 ${
                            route.isAvailable ? 'bg-violet' : 'bg-pink'
                          }`}
                          aria-hidden="true"
                        />
                        <span>{route.provider}</span>
                      </span>
                    ))}
                  </div>
                </td>
                <td className="py-[14px] pr-3 align-middle text-mute font-mono text-[13px]">
                  {model.contextWindow}
                </td>
                <td className="py-[14px] pr-3 align-middle">
                  <div className="flex flex-wrap gap-1">
                    {model.capabilities.map((cap) => (
                      <span
                        key={cap}
                        className="inline-block text-[12px] px-[9px] py-[2px] rounded-pill border border-line text-mute bg-white/40"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </GlassCard>
  );
};
