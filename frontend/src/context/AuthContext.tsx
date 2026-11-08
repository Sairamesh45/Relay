import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from '@/api/client';
import { User } from '@/types';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  error: string | null;
  signInWithGoogle: (idToken?: string) => Promise<void>;
  signInWithEmail: (email: string, name?: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<User | null>;
  isDevMode: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const isDev = Boolean(import.meta.env.DEV);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refreshUser = async (): Promise<User | null> => {
    try {
      const res = await api.auth.me();
      if (res && res.user) {
        const u: User = {
          id: res.user.id,
          email: res.user.email || '',
          fullName: res.user.full_name || 'User',
          avatarUrl: res.user.avatar_url,
        };
        setUser(u);
        return u;
      }
      setUser(null);
      return null;
    } catch {
      setUser(null);
      return null;
    }
  };

  useEffect(() => {
    let mounted = true;

    async function initAuth() {
      try {
        setIsLoading(true);
        setError(null);
        await refreshUser();
      } catch (err: any) {
        if (mounted) {
          setError(err?.message || 'Authentication check failed');
          setUser(null);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    initAuth();

    return () => {
      mounted = false;
    };
  }, []);

  const signInWithEmail = async (email: string, name?: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.auth.email(email.trim(), name);
      if (res && res.user) {
        const u: User = {
          id: res.user.id,
          email: res.user.email || email.trim(),
          fullName: res.user.full_name || email.trim().split('@')[0],
          avatarUrl: res.user.avatar_url,
        };
        setUser(u);
      }
    } catch (err: any) {
      const msg = err?.message || 'Email authentication failed';
      setError(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const signInWithGoogle = async (idToken?: string) => {
    if (!idToken) {
      throw new Error('Google ID token is required for Google Sign-In.');
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.auth.google(idToken);
      if (res && res.user) {
        const u: User = {
          id: res.user.id,
          email: res.user.email || '',
          fullName: res.user.full_name,
          avatarUrl: res.user.avatar_url,
        };
        setUser(u);
      }
    } catch (err: any) {
      const msg = err?.message || 'Google authentication failed';
      setError(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const signOut = async () => {
    setIsLoading(true);
    try {
      await api.auth.logout();
    } catch (err) {
      console.warn('Logout request warning:', err);
    } finally {
      setUser(null);
      setError(null);
      setIsLoading(false);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        error,
        signInWithGoogle,
        signInWithEmail,
        signOut,
        refreshUser,
        isDevMode: isDev,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
