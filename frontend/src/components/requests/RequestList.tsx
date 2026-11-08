import React from 'react';
import { RequestLogItem } from '@/types';

export interface RequestListProps {
  requests: RequestLogItem[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}

export const RequestList: React.FC<RequestListProps> = ({
  requests,
  selectedIndex,
  onSelect,
}) => {
  return (
    <div className="flex flex-col gap-1.5" role="listbox" aria-label="Requests">
      {requests.map((req, idx) => {
        const isSelected = idx === selectedIndex;

        return (
          <div
            key={req.id || `${req.timestamp}-${idx}`}
            role="option"
            aria-selected={isSelected}
            tabIndex={0}
            onClick={() => onSelect(idx)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(idx);
              }
            }}
            className={`p-[14px_16px] rounded-[16px] cursor-pointer grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5 border transition-all duration-200 outline-none select-none ${
              isSelected
                ? 'bg-white border-violet shadow-sm'
                : 'border-transparent hover:bg-white/60 focus-visible:border-violet/60'
            }`}
            data-testid={`request-row-${idx}`}
          >
            <b className="font-semibold text-ink text-[14px] truncate">
              {req.keyName}
            </b>
            <span className="text-mute text-[12.5px] font-mono text-right">
              {req.timestamp}
            </span>
            <span
              className={`text-[12.5px] truncate ${
                req.isRejected ? 'text-pink font-medium' : 'text-mute'
              }`}
            >
              {req.modelServed}
            </span>
            <span className="text-mute text-[12.5px] text-right font-mono">
              {req.latencyFormatted}
            </span>
          </div>
        );
      })}
    </div>
  );
};
