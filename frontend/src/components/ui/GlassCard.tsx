import React from 'react';

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  as?: 'div' | 'section' | 'article' | 'aside';
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  className = '',
  as: Component = 'div',
  ...rest
}) => {
  return (
    <Component
      className={`bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/80 rounded-card p-6 shadow-sm ${className}`}
      {...rest}
    >
      {children}
    </Component>
  );
};
