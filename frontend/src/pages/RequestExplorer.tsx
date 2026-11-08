import React, { useState, useEffect, useCallback, useRef } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { RequestList } from '@/components/requests/RequestList';
import { RequestDetail } from '@/components/requests/RequestDetail';
import { RequestLogItem } from '@/types';
import { api } from '@/api/client';

interface RequestExplorerProps {
  initialRequests?: RequestLogItem[];
}

export const RequestExplorer: React.FC<RequestExplorerProps> = ({ initialRequests }) => {
  const [requests, setRequests] = useState<RequestLogItem[]>(initialRequests || []);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'rejected'>('all');
  const [isLoading, setIsLoading] = useState(!initialRequests);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date>(new Date());
  const isMountedRef = useRef(true);

  const loadRequests = useCallback(async (silent = false) => {
    if (!silent) {
      setIsRefreshing(true);
    }
    try {
      const res = await api.usage.requests({ limit: 100 });
      if (isMountedRef.current && res && Array.isArray(res.logs)) {
        const transformed: RequestLogItem[] = res.logs.map((log: any, idx: number) => {
          const isError = log.status === 'error' || (log.status_code && log.status_code >= 400);
          return {
            id: log.id || `req-${idx}`,
            timestamp: log.created_at
              ? new Date(log.created_at).toLocaleTimeString([], { hour12: false })
              : '',
            keyName: log.virtual_api_key_name || (log.virtual_api_key_id ? `key-${String(log.virtual_api_key_id).slice(0, 6)}` : 'Direct'),
            modelServed: log.gateway_model_id || log.provider_model_id || 'Unknown',
            latencyFormatted: `${log.latency_ms ?? 0} ms`,
            isRejected: isError,
            outcomeText: isError
              ? `Rejected: ${log.error_summary || 'Error'}`
              : `Served by ${log.provider || 'Gateway'} ${log.provider_model_id || ''} in ${log.latency_ms ?? 0} ms`,
            candidates: [
              {
                modelName: log.gateway_model_id || log.provider_model_id || 'Primary Model',
                status: isError ? 'x' : 's',
                reason: isError ? (log.error_summary || 'Execution failed') : 'Selected as primary optimal candidate',
                score: isError ? 0 : 0.95,
              },
            ],
          };
        });
        setRequests(transformed);
        setLastRefreshedAt(new Date());
      }
    } catch {
      // Keep existing requests on transient error
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    if (initialRequests) return;

    loadRequests(false);

    // Auto-polling every 4 seconds for live traffic updates
    const interval = setInterval(() => {
      loadRequests(true);
    }, 4000);

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
    };
  }, [initialRequests, loadRequests]);

  const filteredRequests = requests.filter((r) => {
    const matchesSearch =
      r.keyName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.modelServed.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.timestamp.includes(searchQuery);

    if (!matchesSearch) return false;
    if (statusFilter === 'success') return !r.isRejected;
    if (statusFilter === 'rejected') return r.isRejected;
    return true;
  });

  const selectedRequest =
    filteredRequests[selectedIndex] || filteredRequests[0] || requests[0];

  return (
    <div data-testid="request-explorer-page">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
              Requests
            </h1>
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-pill bg-green-50 border border-green-200 text-green-700 text-xs font-medium">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span>Live Updates</span>
            </div>
          </div>
          <p className="text-mute text-[15px] mt-2">
            Pick a request to inspect its routing evaluation, latency, and token metrics.
            <span className="text-xs text-mute/80 ml-2">
              (Auto-refreshes every 4s · Updated {lastRefreshedAt.toLocaleTimeString()})
            </span>
          </p>
        </div>

        {/* Filter chips, Search & Manual Refresh Button */}
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={() => loadRequests(false)}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-input border border-line bg-white text-ink text-sm hover:bg-marshmallow transition-all disabled:opacity-50 cursor-pointer shadow-sm"
            title="Refresh request audit logs now"
          >
            <svg
              className={`w-4 h-4 text-violet ${isRefreshing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            <span className="font-medium text-xs">
              {isRefreshing ? 'Refreshing…' : 'Refresh'}
            </span>
          </button>

          <input
            type="text"
            placeholder="Search requests..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setSelectedIndex(0);
            }}
            className="w-[180px] px-3.5 py-2 rounded-input border border-line bg-white text-sm outline-none focus:border-violet"
          />

          <div className="flex gap-1.5" role="group" aria-label="Filter status">
            {(['all', 'success', 'rejected'] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                aria-pressed={statusFilter === filter}
                onClick={() => {
                  setStatusFilter(filter);
                  setSelectedIndex(0);
                }}
                className={`px-3 py-1.5 rounded-pill text-[13px] border transition-colors capitalize ${
                  statusFilter === filter
                    ? 'bg-ink text-white border-ink'
                    : 'bg-white/50 text-mute border-line hover:text-ink'
                }`}
              >
                {filter}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 340px Split Layout */}
      {isLoading ? (
        <div className="py-16 text-center text-mute text-sm flex flex-col items-center gap-3">
          <span className="w-6 h-6 rounded-full border-2 border-violet border-t-transparent animate-spin" />
          <span>Loading request logs...</span>
        </div>
      ) : requests.length === 0 ? (
        <div className="py-16 text-center border border-dashed border-line rounded-2xl bg-white/40 flex flex-col items-center gap-3">
          <p className="text-ink font-medium text-base">No requests in audit log</p>
          <p className="text-mute text-sm max-w-[480px]">
            Send a request to <code className="bg-ink/5 px-1.5 py-0.5 rounded text-xs font-mono">/v1/chat/completions</code> with your Virtual Key to start routing traffic.
          </p>
          <button
            type="button"
            onClick={() => loadRequests(false)}
            className="mt-2 inline-flex items-center gap-2 bg-violet text-white text-xs font-medium py-2 px-4 rounded-pill hover:bg-violet-dark transition-all cursor-pointer shadow-sm"
          >
            <svg
              className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            <span>Check for requests now</span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-[340px_1fr] gap-4 items-start max-app:grid-cols-1">
          {/* Left Column: Request List */}
          <GlassCard className="p-2.5 max-h-[750px] overflow-y-auto">
            {filteredRequests.length > 0 ? (
              <RequestList
                requests={filteredRequests}
                selectedIndex={selectedIndex}
                onSelect={(idx) => setSelectedIndex(idx)}
              />
            ) : (
              <div className="p-6 text-center text-mute text-sm">
                No matching requests found.
              </div>
            )}
          </GlassCard>

          {/* Right Column: Detailed Inspection */}
          <GlassCard className="p-6">
            {selectedRequest ? (
              <RequestDetail request={selectedRequest} />
            ) : (
              <div className="p-8 text-center text-mute text-sm">
                Select a request from the list to inspect its routing evaluation.
              </div>
            )}
          </GlassCard>
        </div>
      )}
    </div>
  );
};

export default RequestExplorer;
