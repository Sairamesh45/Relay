import React from 'react';

export interface GlassSkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  height?: string;
  className?: string;
}

/**
 * GlassSkeleton / GlassSkeletonCard
 *
 * Reusable glassmorphic skeleton card strictly adhering to relay.html design tokens:
 * - rounded-[22px]
 * - bg-white/60
 * - backdrop-blur-[22px]
 * - backdrop-saturate-[1.3]
 * - border border-white/80
 *
 * Provides a smooth zero-CLS pulse placeholder during initial cold loads.
 */
export const GlassSkeletonCard: React.FC<GlassSkeletonProps> = ({
  height = 'h-[160px]',
  className = '',
  ...rest
}) => {
  return (
    <div
      data-testid="glass-skeleton-card"
      className={`bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/80 rounded-[22px] p-6 shadow-sm animate-pulse ${height} ${className}`}
      {...rest}
    >
      <div className="w-1/3 h-4 rounded-[8px] bg-ink/10 mb-4" />
      <div className="w-1/2 h-8 rounded-[10px] bg-ink/15 mb-4" />
      <div className="w-full h-3 rounded-[6px] bg-ink/8" />
    </div>
  );
};

export const GlassSkeleton = GlassSkeletonCard;
