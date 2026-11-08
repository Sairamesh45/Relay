import React from 'react';
import { Pill } from '@/components/ui/Pill';
import { CandidateTree } from './CandidateTree';
import { RequestLogItem } from '@/types';

export interface RequestDetailProps {
  request: RequestLogItem;
}

export const RequestDetail: React.FC<RequestDetailProps> = ({ request }) => {
  return (
    <div data-testid="request-detail">
      {/* Detail Header */}
      <div className="flex justify-between items-center gap-3 flex-wrap">
        <h2 className="font-display text-[22px] font-normal text-ink">
          {request.keyName} · {request.timestamp}
        </h2>
        <Pill variant={request.isRejected ? 'warning' : 'default'}>
          {request.isRejected ? 'Rejected' : 'Success'}
        </Pill>
      </div>

      {/* Outcome banner / diagnosis */}
      <p className="text-[13.5px] text-mute my-2 mb-5 leading-normal">
        {request.outcomeText ||
          (request.isRejected
            ? 'No model could take this request.'
            : `Served by ${request.modelServed} in ${request.latencyFormatted}`)}
      </p>

      {/* Candidate ranking evaluation tree */}
      <CandidateTree candidates={request.candidates} />
    </div>
  );
};
