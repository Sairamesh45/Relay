import React from 'react';

export type PillVariant = 'default' | 'warning' | 'neutral' | 'selected';

interface PillProps {
  children: React.ReactNode;
  variant?: PillVariant;
  className?: string;
  hasDot?: boolean;
}

export const Pill: React.FC<PillProps> = ({
  children,
  variant = 'default',
  className = '',
  hasDot = true,
}) => {
  const variantClasses = {
    default: 'bg-[rgba(91,61,255,0.1)] text-violet',
    warning: 'bg-[rgba(255,102,224,0.2)] text-[#B01D8F]',
    neutral: 'bg-[rgba(26,21,48,0.07)] text-mute',
    selected: 'bg-violet text-white',
  }[variant];

  return (
    <span
      className={`inline-flex items-center gap-[6px] px-[11px] py-[3px] rounded-pill text-[12.5px] font-medium transition-colors ${variantClasses} ${className}`}
    >
      {hasDot && (
        <span
          className="w-[6px] height-[6px] h-[6px] rounded-full bg-current shrink-0"
          aria-hidden="true"
        />
      )}
      <span>{children}</span>
    </span>
  );
};
