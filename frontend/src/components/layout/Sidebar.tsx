import React from 'react';
import { NavLink, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';

interface SidebarProps {
  cooldownCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ cooldownCount = 1 }) => {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const navItems = [
    { to: '/app/overview', label: 'Overview' },
    { to: '/app/providers', label: 'Providers', badge: cooldownCount > 0 ? cooldownCount : null },
    { to: '/app/models', label: 'Models' },
    { to: '/app/keys', label: 'API keys' },
    { to: '/app/requests', label: 'Requests' },
    { to: '/app/analytics', label: 'Analytics' },
    { to: '/app/reliability', label: 'Reliability' },
    { to: '/app/settings', label: 'Settings' },
    { to: '/app/docs', label: 'Docs' },
  ];

  const handleSignOut = async (e: React.MouseEvent) => {
    e.preventDefault();
    await signOut();
    navigate('/');
  };

  return (
    <nav
      className="side bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/80 rounded-card p-[20px_14px] flex flex-col gap-[2px] w-[232px] sticky top-[14px] h-[calc(100vh-28px)] max-app:static max-app:w-full max-app:h-auto max-app:flex-row max-app:overflow-x-auto max-app:p-[10px]"
      aria-label="Application Navigation"
    >
      {/* Brand Logo */}
      <Link
        to="/"
        className="flex items-center gap-[10px] font-display font-semibold text-[19px] tracking-[-0.02em] text-ink mx-2 mb-6 max-app:hidden hover:opacity-90 transition-opacity"
      >
        <span className="w-[26px] h-[26px] rounded-[8px] bg-ink grid place-items-center shrink-0">
          <i className="w-[10px] h-[10px] rounded-full bg-gradient-to-br from-violet to-pink block" />
        </span>
        Relay
      </Link>

      {/* Nav items */}
      <div className="flex flex-col gap-[2px] max-app:flex-row max-app:gap-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center justify-between px-3 py-[9px] rounded-[12px] text-[14.5px] transition-colors whitespace-nowrap ${
                isActive
                  ? 'bg-ink text-white font-medium shadow-sm'
                  : 'text-mute hover:text-ink hover:bg-white/40'
              }`
            }
          >
            <span>{item.label}</span>
            {item.badge !== null && item.badge !== undefined && (
              <em className="not-italic text-[11.5px] bg-pink text-ink rounded-pill px-2 py-[1px] font-medium ml-2">
                {item.badge}
              </em>
            )}
          </NavLink>
        ))}
      </div>

      {/* User profile footer */}
      <div className="mt-auto flex items-center gap-[10px] pt-3 px-2 border-t border-line text-[13px] max-app:hidden">
        <span className="w-[30px] h-[30px] rounded-full bg-gradient-to-br from-violet to-pink shrink-0" />
        <span className="flex-1 truncate font-medium text-ink" title={user?.email || 'Account'}>
          {user?.email || 'Account'}
        </span>
        <button
          onClick={handleSignOut}
          className="text-mute hover:text-ink text-[12.5px] cursor-pointer bg-transparent border-0 p-0"
        >
          Sign out
        </button>
      </div>
    </nav>
  );
};
