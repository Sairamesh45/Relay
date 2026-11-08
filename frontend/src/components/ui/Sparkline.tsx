import React from 'react';

interface SparklineProps {
  data: number[];
  color?: string;
  className?: string;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({
  data,
  color = '#5B3DFF',
  className = '',
  height = 30,
}) => {
  if (!data || data.length === 0) return null;

  const max = Math.max(...data, 1);
  const points = data
    .map((v, i) => {
      const x = (i * 100) / (data.length - 1 || 1);
      const y = 28 - (v / max) * 24;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg
      viewBox="0 0 100 30"
      width="100%"
      height={height}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
      />
    </svg>
  );
};
