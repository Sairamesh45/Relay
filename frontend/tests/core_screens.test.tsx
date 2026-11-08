import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/context/ToastContext';
import { AuthProvider } from '../src/context/AuthContext';
import { Providers } from '../src/pages/Providers';
import { Models } from '../src/pages/Models';
import { Keys } from '../src/pages/Keys';
import { RoutingPolicyEditor } from '../src/components/routing/RoutingPolicyEditor';
import { ModelAccessSelector } from '../src/components/routing/ModelAccessSelector';
import { CandidateRankingPreview } from '../src/components/routing/CandidateRankingPreview';
import { api } from '../src/api/client';

// Mock clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn().mockImplementation(() => Promise.resolve()),
  },
});

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AuthProvider>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </AuthProvider>
  );
};

const mockProviders = [
  {
    id: 'google',
    name: 'Google Gemini',
    providerKey: 'google' as const,
    isHealthy: false,
    modelCount: 14,
    medianLatency: '620 ms',
    connectedKeys: '1 key',
    quotaPercent: 62,
    latencyHistory: [5, 6, 5, 7, 6, 8, 6, 5],
    isCoolingDown: true,
    cooldownSeconds: 38,
    cooldownConfirmed: true,
  },
  {
    id: 'groq',
    name: 'Groq',
    providerKey: 'groq' as const,
    isHealthy: true,
    modelCount: 9,
    medianLatency: '310 ms',
    connectedKeys: '2 keys',
    quotaPercent: 40,
    latencyHistory: [4, 3, 4, 3, 3, 4, 3, 3],
    isCoolingDown: false,
    cooldownSeconds: 0,
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    providerKey: 'openrouter' as const,
    isHealthy: true,
    modelCount: 31,
    medianLatency: '740 ms',
    connectedKeys: '1 key',
    quotaPercent: 15,
    latencyHistory: [7, 8, 7, 9, 8, 7, 8, 7],
    isCoolingDown: false,
    cooldownSeconds: 0,
  },
];

const mockModels = [
  {
    id: 'gemini-flash',
    name: 'Gemini Flash',
    technicalName: 'gemini-2.5-flash',
    provider: 'Google Gemini',
    routes: [
      { provider: 'Google Gemini', isAvailable: true, latencyMs: 620 },
    ],
    contextWindow: '1M',
    capabilities: ['Text', 'Tools', 'Image'],
  },
  {
    id: 'gemini-pro',
    name: 'Gemini Pro',
    technicalName: 'gemini-2.5-pro',
    provider: 'Google Gemini',
    routes: [
      { provider: 'Google Gemini', isAvailable: true, latencyMs: 820 },
    ],
    contextWindow: '2M',
    capabilities: ['Text', 'Tools', 'Image'],
  },
  {
    id: 'llama-70b',
    name: 'Llama 3.3 70B',
    technicalName: 'llama-3.3-70b',
    provider: 'Groq',
    routes: [
      { provider: 'Groq', isAvailable: true, latencyMs: 310 },
      { provider: 'Cerebras', isAvailable: true, latencyMs: 180 },
    ],
    contextWindow: '128K',
    capabilities: ['Text', 'Tools'],
  },
  {
    id: 'qwen3-235b',
    name: 'Qwen3 235B',
    technicalName: 'qwen-3-235b',
    provider: 'OpenRouter',
    routes: [
      { provider: 'OpenRouter', isAvailable: true, latencyMs: 740 },
    ],
    contextWindow: '131K',
    capabilities: ['Text', 'Tools'],
  },
];

const mockKeys = [
  {
    id: 'key-1',
    name: 'support-bot',
    keyPrefix: 'sk-relay-4f9a…c21e',
    createdAt: 'Today, 11:12',
    status: 'active' as const,
    dailyLimit: 10000,
    dailyUsagePercent: 62,
    strategy: 'Balanced',
    modelAccess: 'All models' as const,
    expiresAt: 'Never',
    isActive: true,
    weights: { q: 0.5, s: 0.5, a: 0.5 },
  },
  {
    id: 'key-2',
    name: 'research-agent',
    keyPrefix: 'sk-relay-b81d…07aa',
    createdAt: 'Sep 24, 2026',
    status: 'active' as const,
    dailyLimit: 50000,
    dailyUsagePercent: 34,
    strategy: 'Quality first',
    modelAccess: 'Text only' as const,
    expiresAt: 'In 90 days',
    isActive: true,
    weights: { q: 1.0, s: 0.2, a: 0.5 },
  },
  {
    id: 'key-3',
    name: 'notebook',
    keyPrefix: 'sk-relay-93ce…e5b0',
    createdAt: 'Oct 02, 2026',
    status: 'active' as const,
    dailyLimit: 5000,
    dailyUsagePercent: 81,
    strategy: 'Speed first',
    modelAccess: 'Text + Image' as const,
    expiresAt: 'In 30 days',
    isActive: true,
    weights: { q: 0.2, s: 1.0, a: 0.5 },
  },
];

describe('Milestone M5 — Core Product Screens', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('1. Providers View & Connect Drawer', () => {
    it('renders provider cards for Gemini, Groq, and OpenRouter with stats', () => {
      renderWithProviders(<Providers initialProviders={mockProviders} />);

      expect(screen.getByRole('heading', { level: 1, name: 'Providers' })).toBeInTheDocument();
      expect(screen.getByText(/Accounts Relay can route to/i)).toBeInTheDocument();

      // Check the 3 real providers
      expect(screen.getByRole('heading', { level: 2, name: 'Google Gemini' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 2, name: 'Groq' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 2, name: 'OpenRouter' })).toBeInTheDocument();

      // Check status pills
      expect(screen.getByText('Cooling down')).toBeInTheDocument();
      const healthyPills = screen.getAllByText('Healthy');
      expect(healthyPills.length).toBeGreaterThanOrEqual(2);

      // Check stats: model counts, medians, connected keys
      expect(screen.getByText('14')).toBeInTheDocument();
      expect(screen.getByText('620 ms')).toBeInTheDocument();
      expect(screen.getAllByText('1 key').length).toBe(2);
      expect(screen.getByText('9')).toBeInTheDocument();
      expect(screen.getByText('310 ms')).toBeInTheDocument();
      expect(screen.getByText('2 keys')).toBeInTheDocument();
    });

    it('renders live cooldown alert card with countdown timer for Google Gemini', () => {
      renderWithProviders(<Providers initialProviders={mockProviders} />);

      const alertBox = screen.getByRole('alert');
      expect(alertBox).toBeInTheDocument();
      expect(alertBox).toHaveTextContent(/Rate limited/i);
      expect(alertBox).toHaveTextContent(/38s/i);
      expect(alertBox).toHaveTextContent(/Reset time confirmed by the provider/i);
    });

    it('handles "Check now" button clicking with feedback toast', async () => {
      const validateSpy = vi.spyOn(api.providers, 'validate').mockResolvedValue({
        id: 'cred-gemini-001',
        is_valid: true,
      } as any);

      renderWithProviders(<Providers initialProviders={mockProviders} />);

      const checkButtons = screen.getAllByRole('button', { name: 'Check now' });
      fireEvent.click(checkButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Google Gemini connection checked/i)).toBeInTheDocument();
      });
      validateSpy.mockRestore();
    });

    it('opens Connect Provider Drawer, allows selecting provider, entering key, and connecting', async () => {
      const connectSpy = vi.spyOn(api.providers, 'connect').mockResolvedValue({
        id: 'new-cred-123',
        provider: 'groq',
      } as any);

      renderWithProviders(<Providers initialProviders={mockProviders} />);

      // Click "Connect provider" button
      const openDrawerBtn = screen.getByRole('button', { name: 'Connect provider' });
      fireEvent.click(openDrawerBtn);

      // Verify drawer opened
      expect(screen.getByRole('heading', { level: 2, name: 'Connect a provider' })).toBeInTheDocument();
      expect(screen.getByText(/Keys are encrypted using AES-256/i)).toBeInTheDocument();

      // Select provider
      const providerSelect = screen.getByRole('combobox');
      fireEvent.change(providerSelect, { target: { value: 'groq' } });
      expect(providerSelect).toHaveValue('groq');

      // Enter API key
      const keyInput = screen.getByPlaceholderText('Paste your key');
      fireEvent.change(keyInput, { target: { value: 'gsk_test123456789' } });

      // Click "Validate and connect"
      const submitBtn = screen.getByRole('button', { name: 'Validate and connect' });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByText(/Relay found 9 models/i)).toBeInTheDocument();
      });

      // Click Done to close
      const doneBtn = screen.getByRole('button', { name: 'Done' });
      fireEvent.click(doneBtn);

      connectSpy.mockRestore();
    });
  });

  describe('2. Unified Models Catalog View', () => {
    it('renders models table with routes, context window, and capabilities', () => {
      renderWithProviders(<Models initialModels={mockModels} />);

      expect(screen.getByRole('heading', { level: 1, name: 'Models' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Sync models' })).toBeInTheDocument();

      // Table headers
      expect(screen.getByText('Model')).toBeInTheDocument();
      expect(screen.getByText('Routes')).toBeInTheDocument();
      expect(screen.getByText('Context')).toBeInTheDocument();
      expect(screen.getByText('Capabilities')).toBeInTheDocument();

      // Table content
      expect(screen.getByText('Gemini Flash')).toBeInTheDocument();
      expect(screen.getByText('Llama 3.3 70B')).toBeInTheDocument();
      expect(screen.getByText('Qwen3 235B')).toBeInTheDocument();

      // Context windows
      expect(screen.getByText('1M')).toBeInTheDocument();
      expect(screen.getByText('128K')).toBeInTheDocument();
      expect(screen.getByText('131K')).toBeInTheDocument();
    });

    it('filters models dynamically using real-time search query', () => {
      renderWithProviders(<Models initialModels={mockModels} />);

      const searchInput = screen.getByPlaceholderText('Search models');
      fireEvent.change(searchInput, { target: { value: 'Llama' } });

      expect(screen.getByText('Llama 3.3 70B')).toBeInTheDocument();
      expect(screen.queryByText('Gemini Flash')).not.toBeInTheDocument();
      expect(screen.queryByText('Qwen3 235B')).not.toBeInTheDocument();

      // Clear search
      fireEvent.change(searchInput, { target: { value: '' } });
      expect(screen.getByText('Gemini Flash')).toBeInTheDocument();
      expect(screen.getByText('Qwen3 235B')).toBeInTheDocument();
    });

    it('filters models dynamically by capability chips (All, Text, Tools, Image)', () => {
      renderWithProviders(<Models initialModels={mockModels} />);

      const imageChip = screen.getByRole('button', { name: 'Image' });
      const toolsChip = screen.getByRole('button', { name: 'Tools' });
      const allChip = screen.getByRole('button', { name: 'All' });

      // Click Image filter
      fireEvent.click(imageChip);
      expect(imageChip).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('Gemini Flash')).toBeInTheDocument();
      expect(screen.getByText('Gemini Pro')).toBeInTheDocument();
      expect(screen.queryByText('Llama 3.3 70B')).not.toBeInTheDocument();

      // Click Tools filter
      fireEvent.click(toolsChip);
      expect(toolsChip).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('Llama 3.3 70B')).toBeInTheDocument();
      expect(screen.getByText('Qwen3 235B')).toBeInTheDocument();

      // Click All filter
      fireEvent.click(allChip);
      expect(allChip).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByText('Gemini Flash')).toBeInTheDocument();
      expect(screen.getByText('Llama 3.3 70B')).toBeInTheDocument();
    });

    it('triggers sync models when button is clicked', async () => {
      const syncSpy = vi.spyOn(api.models, 'sync').mockResolvedValue({
        sync_id: 'sync-1',
        total_models: 54,
      } as any);

      renderWithProviders(<Models initialModels={mockModels} />);

      const syncBtn = screen.getByRole('button', { name: 'Sync models' });
      fireEvent.click(syncBtn);

      await waitFor(() => {
        expect(screen.getByText('Models synchronized')).toBeInTheDocument();
      });

      syncSpy.mockRestore();
    });
  });

  describe('3. Virtual API Keys View', () => {
    it('renders key cards with masked prefixes, daily limits, and status', () => {
      renderWithProviders(<Keys initialKeys={mockKeys} />);

      expect(screen.getByRole('heading', { level: 1, name: /Virtual Keys|API keys/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Create key' })).toBeInTheDocument();

      // Check keys
      expect(screen.getByText('support-bot')).toBeInTheDocument();
      expect(screen.getByText('sk-relay-4f9a…c21e')).toBeInTheDocument();
      expect(screen.getByText('62%')).toBeInTheDocument();

      expect(screen.getByText('research-agent')).toBeInTheDocument();
      expect(screen.getByText('sk-relay-b81d…07aa')).toBeInTheDocument();
      expect(screen.getByText('34%')).toBeInTheDocument();

      expect(screen.getByText('notebook')).toBeInTheDocument();
      expect(screen.getByText('sk-relay-93ce…e5b0')).toBeInTheDocument();
      expect(screen.getByText('81%')).toBeInTheDocument();
    });

    it('revokes a key with confirmation feedback', async () => {
      const revokeSpy = vi.spyOn(api.keys, 'revoke').mockResolvedValue({} as any);

      renderWithProviders(<Keys initialKeys={mockKeys} />);

      const revokeButtons = screen.getAllByRole('button', { name: 'Revoke' });
      fireEvent.click(revokeButtons[0]);

      await waitFor(() => {
        expect(screen.getByText('Key revoked')).toBeInTheDocument();
      });

      revokeSpy.mockRestore();
    });

    it('opens Create Key Drawer and handles creation and one-time key reveal with copy', async () => {
      renderWithProviders(<Keys initialKeys={mockKeys} />);

      const createBtn = screen.getByRole('button', { name: 'Create key' });
      fireEvent.click(createBtn);

      expect(screen.getByRole('heading', { level: 2, name: 'Create API key' })).toBeInTheDocument();

      // Fill in key name
      const nameInput = screen.getByPlaceholderText('e.g. support-bot');
      fireEvent.change(nameInput, { target: { value: 'analytics-worker' } });

      // Click submit button in drawer form
      const submitButtons = screen.getAllByRole('button', { name: /create key/i });
      const submitBtn = submitButtons[submitButtons.length - 1];
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByText(/Copy your key now/i)).toBeInTheDocument();
      });

      // Verify copy key action
      const copyBtn = screen.getByRole('button', { name: 'Copy key' });
      fireEvent.click(copyBtn);

      expect(screen.getByText('Key copied')).toBeInTheDocument();

      // Click Done
      const doneBtn = screen.getByRole('button', { name: 'Done' });
      fireEvent.click(doneBtn);

      // Verify newly created key appears in list
      expect(screen.getByText('analytics-worker')).toBeInTheDocument();
    });
  });

  describe('4. Routing Policy Editor & Candidate Ranking Preview', () => {
    it('renders 2-column ModelAccessSelector with all 6 modality options', () => {
      const onChange = vi.fn();
      renderWithProviders(
        <ModelAccessSelector value="All models" onChange={onChange} />
      );

      expect(screen.getByText('All models')).toBeInTheDocument();
      expect(screen.getByText('Text only')).toBeInTheDocument();
      expect(screen.getByText('Text + Image')).toBeInTheDocument();
      expect(screen.getByText('Text + Audio')).toBeInTheDocument();
      expect(screen.getByText('Text + Video')).toBeInTheDocument();
      expect(screen.getByText('All modalities')).toBeInTheDocument();

      const textOnlyBtn = screen.getByRole('radio', { name: /Text only/i });
      fireEvent.click(textOnlyBtn);
      expect(onChange).toHaveBeenCalledWith('Text only');
    });

    it('renders CandidateRankingPreview with candidate scores and animated bars', () => {
      renderWithProviders(
        <CandidateRankingPreview
          weights={{ q: 0.5, s: 0.5, a: 0.5 }}
          modelAccess="All models"
        />
      );

      expect(screen.getByText('Who gets the next request')).toBeInTheDocument();
      expect(screen.getByText('Llama 3.3 70B')).toBeInTheDocument();
      expect(screen.getByText('Groq')).toBeInTheDocument();
      expect(screen.getByText('Qwen3 235B')).toBeInTheDocument();
      expect(screen.getByText('Gemini Flash')).toBeInTheDocument();
      expect(screen.getAllByText('Paused').length).toBeGreaterThanOrEqual(1);
    });

    it('opens Routing Policy Editor from Key card Edit button and updates weights dynamically', async () => {
      renderWithProviders(<Keys initialKeys={mockKeys} />);

      const editButtons = screen.getAllByRole('button', { name: 'Edit' });
      fireEvent.click(editButtons[0]); // Edit support-bot

      expect(screen.getByRole('heading', { level: 2, name: 'Edit support-bot' })).toBeInTheDocument();

      // Check presets
      const speedFirstPreset = screen.getByRole('button', { name: 'Speed first' });
      fireEvent.click(speedFirstPreset);
      expect(speedFirstPreset).toHaveAttribute('aria-pressed', 'true');

      // Sliders
      const qualitySlider = screen.getByLabelText('Quality');
      fireEvent.change(qualitySlider, { target: { value: '0.8' } });

      // Save changes
      const saveBtn = screen.getByRole('button', { name: 'Save changes' });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(screen.getByText(/Saved support-bot/i)).toBeInTheDocument();
      });
    });
  });
});
