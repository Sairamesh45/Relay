import React, { useState, useMemo } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';

export interface VolumeTrendsProps {
  requests?: Array<{
    created_at?: string;
    status_code?: number;
    latency_ms?: number;
    [key: string]: any;
  }>;
}

export const VolumeTrends: React.FC<VolumeTrendsProps> = ({ requests = [] }) => {
  const [timeframe, setTimeframe] = useState<'24h' | '7d' | '30d'>('7d');

  const daysData = useMemo(() => {
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const today = new Date();
    const days: { label: string; count: number; dateStr: string }[] = [];

    for (let i = 6; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const dayLabel = dayNames[d.getDay()];
      const dateStr = d.toISOString().split('T')[0];
      days.push({ label: dayLabel, count: 0, dateStr });
    }

    if (requests && requests.length > 0) {
      for (const r of requests) {
        if (r.created_at) {
          const rDate = new Date(r.created_at).toISOString().split('T')[0];
          const bucket = days.find((d) => d.dateStr === rDate);
          if (bucket) {
            bucket.count++;
          }
        }
      }
    }

    const maxCount = Math.max(...days.map((d) => d.count), 1);
    return days.map((d) => ({
      label: d.label,
      count: d.count,
      percent: d.count > 0 ? Math.round((d.count / maxCount) * 100) : 0,
    }));
  }, [requests]);

  const totalReqs = requests?.length || 0;
  const failedReqs =
    requests?.filter((r) => r.status_code && r.status_code >= 400).length || 0;
  const failureRate =
    totalReqs > 0 ? `${((failedReqs / totalReqs) * 100).toFixed(2)}%` : '0.00%';
  const dailyAvg = totalReqs > 0 ? `${(totalReqs / 7).toFixed(1)} reqs` : '0 reqs';
  const peakConcurrency =
    totalReqs > 0
      ? `${Math.min(totalReqs, Math.ceil(totalReqs / 4))} req/s`
      : '0 req/s';

  return (
    <GlassCard className="p-6" data-testid="volume-trends-card">
      <div className="flex justify-between items-center mb-1 flex-wrap gap-2">
        <h2 className="font-display text-[22px] font-normal text-ink">
          Request Volume Trends
        </h2>
        <div className="flex gap-1" role="group" aria-label="Timeframe">
          {(['24h', '7d', '30d'] as const).map((tf) => (
            <button
              key={tf}
              type="button"
              aria-pressed={timeframe === tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 rounded-pill text-[12.5px] border transition-colors ${
                timeframe === tf
                  ? 'bg-ink text-white border-ink'
                  : 'bg-white/50 text-mute border-line hover:text-ink'
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <p className="text-[13px] text-mute mb-5">
        Daily request throughput and concurrency patterns.
      </p>

      {/* Bar Chart Display */}
      <div className="flex items-end gap-3 h-[140px] pt-4 px-2">
        {daysData.map((d) => (
          <div
            key={d.label}
            className="flex-1 flex flex-col justify-end items-center h-full group cursor-pointer"
            title={`${d.label}: ${d.count.toLocaleString()} requests`}
          >
            <div
              style={{ height: `${Math.max(d.percent, 4)}%` }}
              className={`w-full max-w-[48px] rounded-t-[6px] rounded-b-[2px] transition-all duration-200 ${
                d.count > 0
                  ? 'bg-gradient-to-t from-violet to-[#9A86FF] group-hover:brightness-110'
                  : 'bg-ink/8'
              }`}
            />
            <span className="text-[12px] text-mute mt-2 font-mono">
              {d.label}
            </span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4 mt-6 pt-4 border-t border-line text-center">
        <div>
          <span className="text-[12px] text-mute">Peak Concurrency</span>
          <b className="block font-display text-[20px] text-ink mt-0.5">
            {peakConcurrency}
          </b>
        </div>
        <div>
          <span className="text-[12px] text-mute">Daily Average</span>
          <b className="block font-display text-[20px] text-ink mt-0.5">
            {dailyAvg}
          </b>
        </div>
        <div>
          <span className="text-[12px] text-mute">Failure Rate</span>
          <b className="block font-display text-[20px] text-violet mt-0.5">
            {failureRate}
          </b>
        </div>
      </div>
    </GlassCard>
  );
};
