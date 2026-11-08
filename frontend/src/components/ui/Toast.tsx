import React from 'react';
export { useToast, ToastProvider } from '@/context/ToastContext';

interface ToastProps {
  message: string;
  isOpen: boolean;
}

export const Toast: React.FC<ToastProps> = ({ message, isOpen }) => {
  if (!isOpen) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-ink text-white px-5 py-[11px] rounded-[99px] text-sm z-50 shadow-lg"
    >
      {message}
    </div>
  );
};
