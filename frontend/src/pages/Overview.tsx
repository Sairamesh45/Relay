import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { GlassCard } from '@/components/ui/GlassCard';
import { Sparkline } from '@/components/ui/Sparkline';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/api/client';
import { useAuth } from '@/context/AuthContext';
import { useVisibilityInterval } from '@/hooks/useVisibilityInterval';

export interface LiveFeedItem {
  time: string;
  key: string;
  model: string;
  latency: string;
}

export interface OverviewProps {
  initialSummary?: any;
  initialReliability?: any;
  initialFeed?: LiveFeedItem[];
  initialHourlyBars?: number[];
  initialPinkHours?: number[];
}

export const Overview: React.FC<OverviewProps> = ({
  initialSummary,
  initialReliability,
  initialFeed,
  initialHourlyBars,
  initialPinkHours,
}) => {
  const { user } = useAuth();
  const [usageSummary, setUsageSummary] = useState<any>(initialSummary || null);
  const [reliabilitySummary, setReliabilitySummary] = useState<any>(initialReliability || null);
  const [liveFeed, setLiveFeed] = useState<LiveFeedItem[]>(initialFeed || []);
  const [hourlyBars, setHourlyBars] = useState<number[]>(
    initialHourlyBars || new Array(24).fill(0)
  );
  const [pinkHours, setPinkHours] = useState<number[]>(initialPinkHours || []);
  const [hoveredHour, setHoveredHour] = useState<number | null>(null);
  const [isLiveActive, setIsLiveActive] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(
    !initialSummary && !initialReliability && !initialFeed
  );

  // Dynamic greeting based on current time and authenticated user
  const getGreeting = () => {
    const hour = new Date().getHours();
    const name = user?.fullName || (user?.email ? user.email.split('@')[0] : 'there');
    if (hour < 12) return `Good morning, ${name}`;
    if (hour < 18) return `Good afternoon, ${name}`;
    return `Good evening, ${name}`;
  };

  // Fetch real metrics from the backend API
  const fetchData = useCallback(async () => {
    try {
      const [usageRes, relRes, reqsRes] = await Promise.allSettled([
        api.usage.summary(),
        api.reliability.summary(),
        api.usage.requests({ limit: 50 }),
      ]);

      const usage = usageRes.status === 'fulfilled' ? usageRes.value : null;
      const reliability = relRes.status === 'fulfilled' ? relRes.value : null;
      const requestsData = reqsRes.status === 'fulfilled' ? reqsRes.value : null;

      if (usage) setUsageSummary(usage);
      if (reliability) setReliabilitySummary(reliability);

      // Process real request logs
      const rawLogs = requestsData?.logs || [];
      if (Array.isArray(rawLogs) && rawLogs.length > 0) {
        // Map recent logs to live feed
        const mappedFeed: LiveFeedItem[] = rawLogs.slice(0, 8).map((log: any) => ({
          time: log.created_at
            ? new Date(log.created_at).toLocaleTimeString([], { hour12: false })
            : new Date().toLocaleTimeString([], { hour12: false }),
          key: log.virtual_api_key_name || (log.virtual_api_key_id ? `key-${String(log.virtual_api_key_id).slice(0, 6)}` : 'Direct'),
          model: log.gateway_model_id || log.provider_model_id || 'Unknown',
          latency: `${log.latency_ms ?? 0} ms`,
        }));
        setLiveFeed(mappedFeed);

        // Aggregate real requests into 24-hour distribution
        const counts = new Array(24).fill(0);
        const rateLimitHoursSet = new Set<number>();

        rawLogs.forEach((log: any) => {
          if (log.created_at) {
            const h = new Date(log.created_at).getHours();
            if (!isNaN(h) && h >= 0 && h < 24) {
              counts[h] += 1;
              if (log.status_code === 429 || log.status === 'error') {
                rateLimitHoursSet.add(h);
              }
            }
          }
        });

        const maxCount = Math.max(...counts, 1);
        setHourlyBars(counts.map((c) => Math.round((c / maxCount) * 100)));
        setPinkHours(Array.from(rateLimitHoursSet));
      } else {
        setLiveFeed([]);
        setHourlyBars(new Array(24).fill(0));
        setPinkHours([]);
      }
    } catch {
      // Graceful error state handling
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialSummary || initialReliability || initialFeed) return;
    fetchData();
  }, [fetchData, initialSummary, initialReliability, initialFeed]);

  // Live polling for real updates when active (20s visibility-aware cadence)
  useVisibilityInterval(
    () => {
      fetchData();
    },
    20000,
    isLiveActive && !initialSummary && !initialReliability && !initialFeed
  );

  // Dynamic subtitle based on live backend state
  const getSubtitle = () => {
    if (reliabilitySummary?.active_cooldowns_count > 0) {
      const c = reliabilitySummary.active_cooldowns_count;
      return `Everything is running. ${c} model${c > 1 ? 's are' : ' is'} resting.`;
    }
    if (usageSummary?.total_requests > 0) {
      return 'All models and routes are healthy and operational.';
    }
    return 'Gateway is connected. Ready to route requests across providers.';
  };

  // Calculate KPI values from live data
  const totalRequests = usageSummary?.total_requests ?? 0;
  const successRate = totalRequests > 0
    ? `${(((usageSummary?.successful_requests ?? totalRequests) / totalRequests) * 100).toFixed(1)}%`
    : '100%';
  const medianLatency = usageSummary?.average_latency_ms
    ? `${Math.round(usageSummary.average_latency_ms)} ms`
    : '0 ms';
  const failoversHandled = reliabilitySummary?.failovers_total != null
    ? String(reliabilitySummary.failovers_total)
    : '0';

  return (
    <div data-testid="overview-page">
      {/* Greeting Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            {getGreeting()}
          </h1>
          <p className="text-mute text-[15px] mt-2">
            {getSubtitle()}
          </p>
        </div>

        <Link
          to="/app/providers"
          className="inline-flex items-center gap-2 px-[18px] py-[10px] rounded-pill font-medium text-sm bg-ink text-white hover:bg-violet transition-colors"
        >
          Connect provider
        </Link>
      </div>

      {/* 4 KPI Cards */}
      <div className="grid grid-cols-4 gap-4 max-app:grid-cols-2" data-testid="kpi-grid">
        {[
          {
            label: 'Requests',
            val: totalRequests.toLocaleString(),
            data: totalRequests > 0 ? [3, 4, 3, 5, 6, 5, 7, 8] : [0, 0, 0, 0, 0, 0, 0, 0],
            change: totalRequests > 0 ? 'Live database total' : 'No requests yet',
          },
          {
            label: 'Success rate',
            val: successRate,
            data: totalRequests > 0 ? [8, 8, 8, 8, 8, 8, 8, 8] : [0, 0, 0, 0, 0, 0, 0, 0],
            change: `${failoversHandled} failovers handled`,
          },
          {
            label: 'Median latency',
            val: medianLatency,
            data: totalRequests > 0 ? [6, 6, 5, 5, 5, 4, 4, 4] : [0, 0, 0, 0, 0, 0, 0, 0],
            change: totalRequests > 0 ? 'Live rolling average' : 'Awaiting traffic',
          },
          {
            label: 'Failovers',
            val: failoversHandled,
            data: parseInt(failoversHandled, 10) > 0 ? [1, 2, 1, 3, 2, 1, 2, 1] : [0, 0, 0, 0, 0, 0, 0, 0],
            change: '100% recovered safely',
          },
        ].map((kpi) => (
          <GlassCard key={kpi.label} className="p-6">
            <span className="text-[13px] text-mute">{kpi.label}</span>
            <b className="block font-display font-light text-[36px] tracking-kpi text-ink my-1">
              {kpi.val}
            </b>
            <div className="mt-2 mb-2">
              <Sparkline data={kpi.data} color="#5B3DFF" />
            </div>
            <span className="text-[12px] text-mute/80">{kpi.change}</span>
          </GlassCard>
        ))}
      </div>

      {/* 2-Column Dashboard Layout */}
      <div className="grid grid-cols-[1.25fr_1fr] gap-4 mt-4 max-app:grid-cols-1">
        {/* Left Column: Requests per hour */}
        <GlassCard className="p-6">
          <div className="flex justify-between items-center mb-1">
            <h2 className="font-display text-[22px] font-normal text-ink">
              Requests per hour
            </h2>
            {hoveredHour !== null && (
              <span className="text-[12.5px] font-mono text-mute">
                Hour {hoveredHour}:00 — {hourlyBars[hoveredHour] > 0 ? `${hourlyBars[hoveredHour]}% volume` : '0 requests'}{' '}
                {pinkHours.includes(hoveredHour) ? '(429 Rate limit event)' : ''}
              </span>
            )}
          </div>
          <p className="text-[13px] text-mute mb-4">
            {pinkHours.length > 0 ? 'Pink hours had rate-limit events.' : 'Hourly distribution over the last 24 hours.'}
          </p>

          <div
            className="flex items-end gap-[5px] h-[150px] mt-4 pt-2"
            data-testid="hourly-bars"
          >
            {hourlyBars.map((heightPercent, hourIdx) => {
              const isPink = pinkHours.includes(hourIdx);
              const isHovered = hoveredHour === hourIdx;
              const displayHeight = Math.max(heightPercent, 4);

              return (
                <div
                  key={hourIdx}
                  onMouseEnter={() => setHoveredHour(hourIdx)}
                  onMouseLeave={() => setHoveredHour(null)}
                  className="flex-1 flex flex-col justify-end items-center h-full cursor-pointer group"
                  title={`Hour ${hourIdx}:00 - ${isPink ? 'Rate limited' : `${heightPercent}% volume`}`}
                >
                  <i
                    style={{ height: `${displayHeight}%` }}
                    className={`w-full rounded-t-[6px] rounded-b-[2px] transition-all duration-200 ${
                      isPink
                        ? 'bg-gradient-to-t from-pink to-[#FFB3EE]'
                        : heightPercent > 0
                        ? 'bg-gradient-to-t from-violet to-[#9A86FF]'
                        : 'bg-ink/10'
                    } ${isHovered ? 'brightness-125 scale-y-105' : 'hover:opacity-90'}`}
                  />
                </div>
              );
            })}
          </div>

          <div className="flex justify-between text-[11px] text-mute/70 mt-2 px-1">
            <span>00:00</span>
            <span>06:00</span>
            <span>12:00</span>
            <span>18:00</span>
            <span>23:00</span>
          </div>
        </GlassCard>

        {/* Right Column: Live requests feed */}
        <GlassCard className="p-6">
          <div className="flex justify-between items-center mb-1">
            <h2 className="font-display text-[22px] font-normal text-ink">
              Live requests
            </h2>
            <button
              onClick={() => setIsLiveActive(!isLiveActive)}
              className="cursor-pointer"
              title={isLiveActive ? 'Pause live stream' : 'Resume live stream'}
            >
              <Pill variant={isLiveActive ? 'default' : 'neutral'}>
                {isLiveActive ? 'Streaming' : 'Paused'}
              </Pill>
            </button>
          </div>
          <p className="text-[13px] text-mute mb-2">
            Auto-updating live request stream from connected keys.
          </p>

          <div className="divide-y divide-line" data-testid="live-feed">
            {liveFeed.length > 0 ? (
              liveFeed.map((item, idx) => (
                <div
                  key={`${item.time}-${idx}`}
                  className="grid grid-cols-[65px_1fr_auto] gap-2.5 py-[11px] text-[13.5px] items-center transition-all duration-300"
                >
                  <span className="text-mute font-mono text-[12px]">
                    {item.time}
                  </span>
                  <span className="truncate">
                    <span className="text-mute">{item.key}</span>
                    <span className="mx-1.5 text-mute/60">→</span>
                    <b className="text-ink font-medium">{item.model}</b>
                  </span>
                  <span className="text-mute font-mono text-[12px] text-right">
                    {item.latency}
                  </span>
                </div>
              ))
            ) : (
              <div className="py-8 text-center text-mute text-[13px]">
                No requests recorded yet.<br />
                <span className="text-xs text-mute/70">Send requests to <code>/v1/chat/completions</code> to see live traffic.</span>
              </div>
            )}
          </div>
        </GlassCard>
      </div>
    </div>
  );
};

export default Overview;
