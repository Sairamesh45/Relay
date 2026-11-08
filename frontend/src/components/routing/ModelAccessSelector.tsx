import React from 'react';
import { ModelAccessType } from '@/types';

interface ModelAccessOption {
  value: ModelAccessType;
  label: string;
  sub: string;
}

export const MODEL_ACCESS_OPTIONS: ModelAccessOption[] = [
  { value: 'All models', label: 'All models', sub: 'Any supported capability' },
  { value: 'Text only', label: 'Text only', sub: 'Text input and output' },
  { value: 'Text + Image', label: 'Text + Image', sub: 'Text and image input' },
  { value: 'Text + Audio', label: 'Text + Audio', sub: 'Audio input or output' },
  { value: 'Text + Video', label: 'Text + Video', sub: 'Video input' },
  { value: 'All modalities', label: 'All modalities', sub: 'All supported modalities' },
];

interface ModelAccessSelectorProps {
  value: ModelAccessType;
  onChange: (value: ModelAccessType) => void;
  className?: string;
}

export const ModelAccessSelector: React.FC<ModelAccessSelectorProps> = ({
  value,
  onChange,
  className = '',
}) => {
  return (
    <div className={className}>
      <div className="flex justify-between text-[13px] text-mute mb-[10px] mt-[18px]">
        <span>Model access</span>
        <span>Allowed input types</span>
      </div>

      <div
        role="radiogroup"
        aria-label="Model access profile"
        className="grid grid-cols-2 gap-[10px] max-app:grid-cols-1"
      >
        {MODEL_ACCESS_OPTIONS.map((opt) => {
          const isChecked = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={isChecked}
              onClick={() => onChange(opt.value)}
              className={`text-left p-[14px] px-4 rounded-[14px] border transition-all duration-200 cursor-pointer block ${
                isChecked
                  ? 'border-violet bg-[rgba(91,61,255,0.07)] shadow-[0_0_0_1px_#5B3DFF]'
                  : 'border-line bg-white hover:border-ink'
              }`}
            >
              <b className="block font-semibold text-[14.5px] text-ink leading-tight">
                {opt.label}
              </b>
              <span className="text-[13px] text-mute leading-snug">{opt.sub}</span>
            </button>
          );
        })}
      </div>

      <p className="text-[13px] text-mute mt-3 leading-relaxed">
        A model is eligible only when its capabilities and the connected provider adapter support the request.
      </p>
    </div>
  );
};
