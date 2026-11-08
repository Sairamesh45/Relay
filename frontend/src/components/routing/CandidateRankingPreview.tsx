import React, { useMemo } from 'react';
import { RoutingWeights, ModelAccessType } from '@/types';

export interface CandidateItem {
  id: string;
  modelName: string;
  provider: string;
  quality: number;
  speed: number;
  isAvailable: boolean;
  score: number;
  isPaused?: boolean;
}

// Base reference candidate dataset matching relay.html
const REFERENCE_MODELS = [
  { name: 'Gemini Flash', provider: 'Google Gemini', q: 0.9, s: 0.6, avail: false, isPaused: true },
  { name: 'Llama 3.3 70B', provider: 'Groq', q: 0.78, s: 0.9, avail: true, isPaused: false },
  { name: 'Gemini Pro', provider: 'Google Gemini', q: 0.95, s: 0.4, avail: false, isPaused: true },
  { name: 'Qwen3 235B', provider: 'OpenRouter', q: 0.85, s: 0.5, avail: true, isPaused: false },
];

interface CandidateRankingPreviewProps {
  weights: RoutingWeights;
  modelAccess?: ModelAccessType;
  apiCandidates?: CandidateItem[];
  isLoading?: boolean;
}

export const CandidateRankingPreview: React.FC<CandidateRankingPreviewProps> = ({
  weights,
  modelAccess = 'All models',
  apiCandidates,
  isLoading = false,
}) => {
  // Compute rankings dynamically based on weights if API candidates are not provided
  const rankedCandidates = useMemo(() => {
    if (apiCandidates && apiCandidates.length > 0) {
      return apiCandidates;
    }

    const totalWeight = weights.q + weights.s + weights.a || 1;

    return REFERENCE_MODELS.map((m, idx) => {
      // Calculate weighted score
      // Score = (Wq * quality + Ws * speed + Wa * availability) / totalWeight
      const availScore = m.avail ? 1 : 0;
      const computedScore = m.avail
        ? (weights.q * m.q + weights.s * m.s + weights.a * availScore) / totalWeight
        : 0;

      return {
        id: `m-${idx}`,
        modelName: m.name,
        provider: m.provider,
        quality: m.q,
        speed: m.s,
        isAvailable: m.avail,
        isPaused: m.isPaused,
        score: computedScore,
      };
    }).sort((a, b) => b.score - a.score);
  }, [weights, modelAccess, apiCandidates]);

  return (
    <div className="mt-2">
      <div className="flex justify-between items-center text-[13px] text-mute mb-2">
        <span>Who gets the next request</span>
        <span>Simulated rank</span>
      </div>

      <div className="border-t border-line divide-y divide-line">
        {isLoading ? (
          <div className="py-4 text-center text-mute text-sm">Evaluating candidates…</div>
        ) : (
          rankedCandidates.map((cand, idx) => {
            const isFirst = idx === 0 && !cand.isPaused;
            const scorePercent = Math.min(100, Math.max(0, Math.round(cand.score * 100)));

            return (
              <div
                key={cand.id || cand.modelName}
                className="grid grid-cols-[28px_1fr_50px] gap-3 items-center py-[14px]"
              >
                {/* Rank Number */}
                <span
                  className={`font-display font-light text-[24px] ${
                    isFirst ? 'text-violet font-normal' : 'text-mute'
                  }`}
                >
                  {cand.isPaused ? '–' : idx + 1}
                </span>

                {/* Candidate Information & Animated Score Bar */}
                <div className="min-w-0 pr-2">
                  <div className="flex items-baseline gap-2 truncate">
                    <b className="font-semibold text-[14px] text-ink">{cand.modelName}</b>
                    <span className="text-[12.5px] text-mute">{cand.provider}</span>
                  </div>

                  <div className="h-[6px] rounded-[9px] bg-ink/8 overflow-hidden mt-2 max-w-[240px]">
                    <i
                      className="block h-full rounded-[9px] bg-gradient-to-r from-violet to-pink transition-all duration-300"
                      style={{ width: `${cand.isPaused ? 0 : scorePercent}%` }}
                    />
                  </div>
                </div>

                {/* Numerical Score / Paused Pill */}
                <span
                  className={`text-[13px] text-right ${
                    cand.isPaused ? 'text-mute' : 'font-medium text-ink'
                  }`}
                >
                  {cand.isPaused ? 'Paused' : cand.score.toFixed(2)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
