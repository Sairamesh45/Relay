import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Landing } from '../src/pages/Landing';
import { Auth } from '../src/pages/Auth';
import { AuthProvider } from '../src/context/AuthContext';
import { ToastProvider } from '../src/context/ToastContext';
import { Sidebar } from '../src/components/layout/Sidebar';

vi.mock('@react-oauth/google', () => ({
  GoogleLogin: () => <button>Continue with Google</button>,
  GoogleOAuthProvider: ({ children }: any) => <>{children}</>,
}));

describe('Landing Page', () => {
  it('renders headline and hero section matching relay.html', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { level: 1, name: /One API/i })).toBeInTheDocument();
    expect(screen.getByText(/Connect the AI accounts you already have/i)).toBeInTheDocument();
    expect(screen.getByText(/See every routing decision/i)).toBeInTheDocument();
  });

  it('switches routing strategies dynamically on button click', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );

    const qualityBtn = screen.getByRole('button', { name: 'Quality' });
    const speedBtn = screen.getByRole('button', { name: 'Speed' });

    // Initial balanced strategy
    expect(screen.getByText(/Gemini Flash ranked first but is rate limited/i)).toBeInTheDocument();

    // Click Quality
    fireEvent.click(qualityBtn);
    expect(qualityBtn).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Gemini Flash is paused, so the next preferred model/i)).toBeInTheDocument();

    // Click Speed
    fireEvent.click(speedBtn);
    expect(speedBtn).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Cerebras Llama has the lowest observed latency/i)).toBeInTheDocument();
  });

  it('renders OpenAI python SDK code block snippet', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    );

    expect(screen.getByText(/Change the URL. Keep your code./i)).toBeInTheDocument();
    expect(screen.getByText('from')).toBeInTheDocument();
    expect(screen.getByText(/Served by Groq. Gemini was rate limited./i)).toBeInTheDocument();
  });
});

describe('Auth Screen', () => {
  it('renders split layout with art panel and Google sign in button', () => {
    render(
      <AuthProvider>
        <MemoryRouter>
          <Auth />
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.getByRole('heading', { level: 2, name: /Welcome back/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Continue with Google/i })).toBeInTheDocument();
    expect(screen.getByText(/Sessions are secured via HttpOnly cookies/i)).toBeInTheDocument();
  });
});

describe('Sidebar Navigation', () => {
  it('renders all core navigation links and cooldown badge', () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/app/overview']}>
          <Sidebar cooldownCount={1} />
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Providers')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument(); // notification badge
    expect(screen.getByText('Models')).toBeInTheDocument();
    expect(screen.getByText('API keys')).toBeInTheDocument();
    expect(screen.getByText('Requests')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });
});
