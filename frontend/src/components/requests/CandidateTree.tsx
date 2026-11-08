import React from 'react';
import { Pill } from '@/components/ui/Pill';
import { CandidateBreakdownItem } from '@/types';

export interface CandidateTreeProps {
  candidates: CandidateBreakdownItem[];
}

export const CandidateTree: React.FC<CandidateTreeProps> = ({ candidates }) => {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="text-[13px] text-mute py-4 border-t border-line">
        No candidate evaluation details recorded for this request.
      </div>
    );
  }

  return (
    <div className="space-y-0" data-testid="candidate-tree">
      <div className="text-[12px] font-medium text-mute uppercase tracking-wider mb-2">
        Candidate Evaluation
      </div>
      {candidates.map((cand: any, idx) => {
        const isSelected = cand.status === 's' || cand.status === 'selected';
        const isSkipped =
          cand.status === 'x' ||
          cand.status === 'skipped' ||
          cand.status === 'rate_limited';
        const isEligible = cand.status === 'o' || cand.status === 'eligible';
        const reasonText = cand.reason || cand.statusDetails || '';

        return (
          <div
            key={`${cand.modelName}-${idx}`}
            className="grid grid-cols-[14px_1fr] gap-[14px] py-4 border-t border-line items-start"
            data-testid={`candidate-item-${idx}`}
          >
            {/* Status dot indicator matching relay.html (.dot, .dot.s, .dot.x) */}
            <span
              className={`w-3 h-3 rounded-full mt-1.5 transition-colors ${
                isSelected
                  ? 'bg-violet border-2 border-violet'
                  : isSkipped
                  ? 'bg-pink border-2 border-pink'
                  : 'bg-transparent border-2 border-mute/50'
              }`}
              title={
                isSelected
                  ? 'Selected model'
                  : isSkipped
                  ? 'Skipped or rate limited'
                  : 'Eligible alternative'
              }
            />

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <b className="font-semibold text-ink text-[14.5px]">
                  {cand.modelName}
                </b>
                {isSelected && <Pill variant="default">Selected</Pill>}
                {isSkipped && <Pill variant="warning">Skipped</Pill>}
                {isEligible && <Pill variant="neutral">Eligible</Pill>}
              </div>

              <div className="text-[13px] text-mute mt-1 leading-relaxed">
                {reasonText}
              </div>

              {cand.score > 0 && (
                <div className="flex items-center gap-3 mt-2">
                  <div className="flex-1 max-w-[240px] h-[6px] rounded-[9px] bg-ink/8 overflow-hidden">
                    <div
                      className="h-full rounded-[9px] bg-gradient-to-r from-violet to-pink transition-all duration-300"
                      style={{ width: `${Math.min(cand.score * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-[12.5px] font-mono text-mute">
                    {cand.score.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
