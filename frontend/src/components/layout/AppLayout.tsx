import React from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { useAuth } from '@/context/AuthContext';

export const AppLayout: React.FC = () => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="ambient-bg min-h-screen grid place-items-center font-body text-ink">
        <div className="flex flex-col items-center gap-3">
          <span className="w-8 h-8 rounded-full border-2 border-violet border-t-transparent animate-spin" />
          <span className="text-mute text-sm">Verifying session…</span>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="ambient-bg min-h-screen text-ink font-body">
      <div className="grid grid-cols-[232px_1fr] gap-5 p-[14px] max-app:grid-cols-1 max-w-[1400px] mx-auto">
        <Sidebar cooldownCount={1} />
        <main className="max-w-[1120px] w-full p-[26px_28px_70px] max-app:p-[16px_8px]">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
