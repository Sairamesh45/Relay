import React, { useEffect } from 'react';

interface SlideDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const SlideDrawer: React.FC<SlideDrawerProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-hidden={!isOpen}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
      className={`fixed inset-0 bg-ink/30 backdrop-blur-[3px] z-50 transition-opacity duration-250 ${
        isOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
      }`}
    >
      <div
        className={`absolute right-[14px] top-[14px] bottom-[14px] w-[min(440px,calc(100%-28px))] bg-paper rounded-sheet p-[30px] overflow-y-auto shadow-2xl transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-6'
        }`}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="float-right border-0 bg-transparent text-[22px] text-mute hover:text-ink cursor-pointer leading-none p-1 -mt-1 -mr-1"
        >
          &times;
        </button>

        {title && (
          <div className="mb-4">
            <h2 className="font-display text-[22px] font-normal leading-appHeadline text-ink">
              {title}
            </h2>
            {subtitle && <p className="text-[13px] text-mute mt-[6px]">{subtitle}</p>}
          </div>
        )}

        <div className="clear-both">{children}</div>
      </div>
    </div>
  );
};
