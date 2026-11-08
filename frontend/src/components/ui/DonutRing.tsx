import React from 'react';

interface DonutRingProps {
  percent: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export const DonutRing: React.FC<DonutRingProps> = ({
  percent,
  size = 76,
  strokeWidth = 3,
  className = '',
}) => {
  const strokeColor = percent > 55 ? '#FF66E0' : '#5B3DFF';
  const dashLength = percent * 0.942;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      className={className}
      role="img"
      aria-label={`Quota used: ${percent}%`}
    >
      <circle
        cx="18"
        cy="18"
        r="15"
        fill="none"
        stroke="rgba(26,21,48,.08)"
        strokeWidth={strokeWidth}
      />
      <circle
        cx="18"
        cy="18"
        r="15"
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={`${dashLength} 100`}
        transform="rotate(-90 18 18)"
      />
      <text
        x="18"
        y="21"
        textAnchor="middle"
        className="font-body font-medium text-[8px] fill-ink"
      >
        {percent}%
      </text>
    </svg>
  );
};
