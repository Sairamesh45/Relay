import React from 'react';

export type CapabilityFilter = 'All' | 'Text' | 'Tools' | 'Image';

interface ModelSearchFilterProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  selectedCapability: CapabilityFilter;
  onCapabilityChange: (capability: CapabilityFilter) => void;
}

const CAPABILITY_CHIPS: CapabilityFilter[] = ['All', 'Text', 'Tools', 'Image'];

export const ModelSearchFilter: React.FC<ModelSearchFilterProps> = ({
  searchQuery,
  onSearchChange,
  selectedCapability,
  onCapabilityChange,
}) => {
  return (
    <div className="flex gap-[10px] mb-4 flex-wrap items-center">
      <input
        type="text"
        placeholder="Search models"
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
        className="max-w-[260px] w-full px-[14px] py-[9px] rounded-input border border-line bg-white text-ink text-sm placeholder:text-mute focus:border-violet focus:outline-none transition-colors"
      />
      <div className="flex gap-[6px]" role="group" aria-label="Filter models by capability">
        {CAPABILITY_CHIPS.map((chip) => {
          const isSelected = selectedCapability === chip;
          return (
            <button
              key={chip}
              type="button"
              aria-pressed={isSelected}
              onClick={() => onCapabilityChange(chip)}
              className={`px-[14px] py-[7px] rounded-pill text-[13.5px] cursor-pointer transition-all duration-200 border ${
                isSelected
                  ? 'bg-ink text-white border-ink font-medium shadow-sm'
                  : 'bg-white/50 border-line text-mute hover:text-ink hover:border-ink'
              }`}
            >
              {chip}
            </button>
          );
        })}
      </div>
    </div>
  );
};
