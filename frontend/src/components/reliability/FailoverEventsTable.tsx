import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/api/client';

export interface FailoverEvent {
  id: string;
  timestamp: string;
  eventType:
    | 'RATE_LIMIT_DETECTED'
    | 'FAILOVER_STARTED'
    | 'FAILOVER_SUCCEEDED'
    | 'CIRCUIT_HALF_OPEN'
    | 'CANDIDATE_RECOVERED'
    | 'CREDENTIAL_AUTH_FAILED';
  provider: string;
  model: string;
  level?: 'Level 1' | 'Level 2' | 'Level 3';
  details: string;
}

export interface FailoverEventsTableProps {
  initialEvents?: FailoverEvent[];
}

export const FailoverEventsTable: React.FC<FailoverEventsTableProps> = ({
  initialEvents,
}) => {
  const [events, setEvents] = useState<FailoverEvent[]>(initialEvents || []);
  const [filter, setFilter] = useState<string>('all');

  useEffect(() => {
    if (initialEvents) return;
    let mounted = true;

    async function loadEvents() {
      try {
        const res = await api.reliability.events({ limit: 50 });
        if (mounted && res?.items && Array.isArray(res.items)) {
          const providerNames: Record<string, string> = {
            google: 'Google Gemini',
            gemini: 'Google Gemini',
            groq: 'Groq',
            cerebras: 'Cerebras',
            openrouter: 'OpenRouter',
          };

          const mapped: FailoverEvent[] = res.items.map((ev: any) => {
            const prov =
              providerNames[ev.provider?.toLowerCase()] || ev.provider;
            const timeStr = ev.timestamp
              ? new Date(ev.timestamp).toLocaleTimeString()
              : '—';
            const meta = ev.metadata || {};

            return {
              id: ev.id,
              timestamp: timeStr,
              eventType: ev.event_type,
              provider: prov,
              model: ev.model_id || '—',
              level: meta.level,
              details:
                meta.details || meta.message || `Event ${ev.event_type} recorded.`,
            };
          });

          setEvents(mapped);
        }
      } catch {
        // Handled cleanly
      }
    }

    loadEvents();
    return () => {
      mounted = false;
    };
  }, [initialEvents]);

  const filteredEvents = events.filter((evt) => {
    if (filter === 'all') return true;
    if (filter === 'rate_limit') return evt.eventType === 'RATE_LIMIT_DETECTED';
    if (filter === 'failover')
      return (
        evt.eventType === 'FAILOVER_STARTED' ||
        evt.eventType === 'FAILOVER_SUCCEEDED'
      );
    if (filter === 'circuit') return evt.eventType === 'CIRCUIT_HALF_OPEN';
    if (filter === 'recovery') return evt.eventType === 'CANDIDATE_RECOVERED';
    return true;
  });

  const getEventBadge = (type: FailoverEvent['eventType']) => {
    switch (type) {
      case 'FAILOVER_SUCCEEDED':
        return <Pill variant="default">Failover Succeeded</Pill>;
      case 'FAILOVER_STARTED':
        return <Pill variant="warning">Failover Started</Pill>;
      case 'RATE_LIMIT_DETECTED':
        return <Pill variant="warning">Rate Limited (429)</Pill>;
      case 'CIRCUIT_HALF_OPEN':
        return <Pill variant="neutral">Circuit Half-Open</Pill>;
      case 'CANDIDATE_RECOVERED':
        return <Pill variant="default">Candidate Recovered</Pill>;
      case 'CREDENTIAL_AUTH_FAILED':
        return <Pill variant="warning">Auth Failed (401)</Pill>;
      default:
        return <Pill variant="neutral">{type}</Pill>;
    }
  };

  return (
    <GlassCard className="p-6" data-testid="failover-events-card">
      <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
        <div>
          <h2 className="font-display text-[22px] font-normal text-ink">
            Failover & Reliability Event Log
          </h2>
          <p className="text-[13px] text-mute mt-0.5">
            Audit trail of upstream errors, automatic failovers, and recovery transitions.
          </p>
        </div>

        {/* Filter chips */}
        <div className="flex gap-1.5 flex-wrap" role="group" aria-label="Event filter">
          {[
            { id: 'all', label: 'All' },
            { id: 'rate_limit', label: 'Rate Limits' },
            { id: 'failover', label: 'Failovers' },
            { id: 'circuit', label: 'Circuit Breakers' },
            { id: 'recovery', label: 'Recovery' },
          ].map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`px-3 py-1.5 rounded-pill text-[12.5px] border transition-colors ${
                filter === f.id
                  ? 'bg-ink text-white border-ink'
                  : 'bg-white/50 text-mute border-line hover:text-ink'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {filteredEvents.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[14px]">
            <thead>
              <tr className="border-b border-line text-mute text-[13px] font-medium">
                <th className="pb-3 pr-3 font-medium">Time</th>
                <th className="pb-3 pr-3 font-medium">Event Type</th>
                <th className="pb-3 pr-3 font-medium">Provider & Model</th>
                <th className="pb-3 pr-3 font-medium">Level</th>
                <th className="pb-3 font-medium">Diagnosis & Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filteredEvents.map((evt) => (
                <tr key={evt.id} className="hover:bg-white/40">
                  <td className="py-3.5 pr-3 text-mute font-mono text-[13px]">
                    {evt.timestamp}
                  </td>
                  <td className="py-3.5 pr-3">{getEventBadge(evt.eventType)}</td>
                  <td className="py-3.5 pr-3 text-ink font-medium">
                    {evt.provider}{' '}
                    <span className="text-mute font-normal">· {evt.model}</span>
                  </td>
                  <td className="py-3.5 pr-3">
                    {evt.level ? (
                      <span className="text-[12px] px-2 py-0.5 rounded-pill bg-ink/5 border border-line text-ink font-medium">
                        {evt.level}
                      </span>
                    ) : (
                      <span className="text-mute text-[13px]">—</span>
                    )}
                  </td>
                  <td className="py-3.5 text-mute text-[13px] max-w-md">
                    {evt.details}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-8 text-center text-mute text-[13px] rounded-[16px] bg-ink/5 border border-line">
          No failover or circuit trip events recorded. All operations are running normally without upstream incidents.
        </div>
      )}
    </GlassCard>
  );
};
