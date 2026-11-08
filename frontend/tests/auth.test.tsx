import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { AuthProvider, useAuth } from '@/context/AuthContext';
import { Auth } from '@/pages/Auth';
import { api } from '@/api/client';

// Mock the API client
vi.mock('@/api/client', () => {
  return {
    api: {
      auth: {
        me: vi.fn(),
        google: vi.fn(),
        refresh: vi.fn(),
        logout: vi.fn(),
      },
    },
    apiRequest: vi.fn(),
    setAuthToken: vi.fn(),
    setDevUser: vi.fn(),
  };
});

// Mock @react-oauth/google GoogleLogin button
vi.mock('@react-oauth/google', () => ({
  GoogleOAuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  GoogleLogin: ({ onSuccess }: { onSuccess: (res: any) => void }) => (
    <button
      data-testid="mock-google-login"
      onClick={() => onSuccess({ credential: 'mock-google-id-token-xyz' })}
    >
      Sign in with Google Mock
    </button>
  ),
}));

const TestConsumer: React.FC = () => {
  const { user, isLoading, signInWithGoogle, signOut } = useAuth();
  if (isLoading) return <div>Loading...</div>;
  return (
    <div>
      <div data-testid="user-email">{user ? user.email : 'No user'}</div>
      <button onClick={() => signInWithGoogle('test-token')}>Sign In</button>
      <button onClick={() => signOut()}>Sign Out</button>
    </div>
  );
};

describe('Google Sign-In Authentication & AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initializes with unauthenticated state when /auth/me returns 401', async () => {
    vi.mocked(api.auth.me).mockRejectedValueOnce(new Error('Unauthorized'));

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-email')).toHaveTextContent('No user');
    });
  });

  it('restores user profile when /auth/me returns active session', async () => {
    vi.mocked(api.auth.me).mockResolvedValueOnce({
      user: {
        id: 'user-uuid-1',
        email: 'user@example.com',
        full_name: 'Example User',
        avatar_url: 'https://avatar.url/pic.jpg',
        is_active: true,
        created_at: new Date().toISOString(),
      },
      status: 'ok',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com');
    });
  });

  it('signs in with Google ID token, calls api.auth.google, and updates user', async () => {
    vi.mocked(api.auth.me).mockRejectedValueOnce(new Error('Unauthorized'));
    vi.mocked(api.auth.google).mockResolvedValueOnce({
      user: {
        id: 'user-google-1',
        email: 'google-user@example.com',
        full_name: 'Google User',
        avatar_url: null,
        is_active: true,
        created_at: new Date().toISOString(),
      },
      status: 'ok',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-email')).toHaveTextContent('No user');
    });

    fireEvent.click(screen.getByText('Sign In'));

    await waitFor(() => {
      expect(api.auth.google).toHaveBeenCalledWith('test-token');
      expect(screen.getByTestId('user-email')).toHaveTextContent('google-user@example.com');
    });
  });

  it('signs out user by calling api.auth.logout and clearing state', async () => {
    vi.mocked(api.auth.me).mockResolvedValueOnce({
      user: {
        id: 'user-google-1',
        email: 'google-user@example.com',
        is_active: true,
        created_at: new Date().toISOString(),
      },
      status: 'ok',
    });
    vi.mocked(api.auth.logout).mockResolvedValueOnce({ status: 'ok' });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-email')).toHaveTextContent('google-user@example.com');
    });

    fireEvent.click(screen.getByText('Sign Out'));

    await waitFor(() => {
      expect(api.auth.logout).toHaveBeenCalled();
      expect(screen.getByTestId('user-email')).toHaveTextContent('No user');
    });
  });

  it('renders Google Login button on Auth screen and triggers sign in', async () => {
    vi.mocked(api.auth.me).mockRejectedValueOnce(new Error('Unauthorized'));
    vi.mocked(api.auth.google).mockResolvedValueOnce({
      user: {
        id: 'user-google-9',
        email: 'signedin@google.com',
        is_active: true,
        created_at: new Date().toISOString(),
      },
      status: 'ok',
    });

    render(
      <GoogleOAuthProvider clientId="test-client-id">
        <AuthProvider>
          <MemoryRouter initialEntries={['/login']}>
            <Routes>
              <Route path="/login" element={<Auth />} />
              <Route path="/app/overview" element={<div>Dashboard Overview</div>} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </GoogleOAuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('mock-google-login')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('mock-google-login'));

    await waitFor(() => {
      expect(api.auth.google).toHaveBeenCalledWith('mock-google-id-token-xyz');
      expect(screen.getByText('Dashboard Overview')).toBeInTheDocument();
    });
  });
});
