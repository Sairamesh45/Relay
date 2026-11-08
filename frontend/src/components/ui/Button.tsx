import React from 'react';

export type ButtonVariant = 'dark' | 'line' | 'pink' | 'google';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  children: React.ReactNode;
  className?: string;
  asAnchor?: boolean;
  href?: string;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'dark',
  children,
  className = '',
  asAnchor = false,
  href,
  ...rest
}) => {
  const baseClasses =
    'inline-flex items-center justify-center gap-2 rounded-pill font-medium text-sm transition-all duration-200 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed';

  const variantClasses = {
    dark: 'bg-ink text-white hover:bg-violet active:scale-[0.98] px-[18px] py-[10px]',
    line: 'bg-white/50 border border-line text-ink hover:border-ink px-[18px] py-[10px]',
    pink: 'bg-pink text-ink hover:opacity-90 px-[20px] py-[11px]',
    google: 'bg-white border border-line text-ink hover:border-ink w-full justify-center px-4 py-[13px] shadow-sm',
  }[variant];

  if (asAnchor && href) {
    return (
      <a href={href} className={`${baseClasses} ${variantClasses} ${className}`}>
        {children}
      </a>
    );
  }

  return (
    <button className={`${baseClasses} ${variantClasses} ${className}`} {...rest}>
      {children}
    </button>
  );
};
