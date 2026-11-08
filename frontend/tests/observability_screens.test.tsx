import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../src/context/AuthContext';
import { ToastProvider } from '../src/context/ToastContext';
import { Overview } from '../src/pages/Overview';
import { RequestExplorer } from '../src/pages/RequestExplorer';
import { Analytics } from '../src/pages/Analytics';
import { Reliability } from '../src/pages/Reliability';
import { Settings } from '../src/pages/Settings';
import { Docs } from '../src/pages/Docs';
import { TokenMetrics } from '../src/components/analytics/TokenMetrics';
import { CostBreakdown } from '../src/components/analytics/CostBreakdown';
import { VolumeTrends } from '../src/components/analytics/VolumeTrends';
import { ProviderHealthMatrix } from '../src/components/reliability/ProviderHealthMatrix';
import { QuotaGauges } from '../src/components/reliability/QuotaGauges';
import { CircuitBreakers } from '../src/components/reliability/CircuitBreakers';
import { FailoverEventsTable } from '../src/components/reliability/FailoverEventsTable';
import { RequestLogItem } from '@/types';

// Helper wrapper providing context providers
const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AuthProvider>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </AuthProvider>
  );
};

const mockOverviewSummary = {
  total_requests: 48210,
  successful_requests: 48117,
  failed_requests: 93,
  average_latency_ms: 412,
  failovers_handled: 93,
  active_cooldowns: 1,
};

const mockReliabilitySummary = {
  uptime_percent: 99.8,
  failovers_total: 93,
  active_cooldowns: 1,
  open_circuits: 0,
  active_cooldowns_count: 1,
  failover_success_count: 93,
  failover_success_rate: 99.8,
};

const mockLiveFeed = [
  { time: '14:02:11', key: 'support-bot', model: 'Groq Llama', latency: '412 ms' },
  { time: '14:02:08', key: 'research-agent', model: 'Gemini Pro', latency: '820 ms' },
];

const mockHourlyBars = new Array(24).fill(50);

const mockRequests: RequestLogItem[] = [
  {
    id: 'req-0',
    timestamp: '14:02:11',
    keyName: 'support-bot',
    modelServed: 'Groq Llama',
    latencyFormatted: '412 ms',
    isRejected: false,
    outcomeText: 'Served by Groq Llama in 412 ms after Gemini rate limit.',
    candidates: [
      {
        modelName: 'Groq Llama',
        providerName: 'Groq',
        latencyMs: 412,
        costEstimate: '$0.00',
        scoreFormatted: '0.94',
        status: 'selected',
        statusDetails: 'Served in 412 ms',
      },
      {
        modelName: 'Gemini Flash',
        providerName: 'Google Gemini',
        latencyMs: 0,
        costEstimate: '$0.00',
        scoreFormatted: '0.00',
        status: 'rate_limited',
        statusDetails: 'Rate limited. Cooling down (38s).',
      },
      {
        modelName: 'Cerebras Llama',
        providerName: 'Cerebras',
        latencyMs: 180,
        costEstimate: '$0.00',
        scoreFormatted: '0.91',
        status: 'skipped',
        statusDetails: 'Ranked #2. Kept as warm backup.',
      },
    ],
  },
  {
    id: 'req-1',
    timestamp: '14:02:08',
    keyName: 'research-agent',
    modelServed: 'Gemini Pro',
    latencyFormatted: '820 ms',
    isRejected: false,
    outcomeText: 'Served by Gemini Pro in 820 ms',
    candidates: [],
  },
  {
    id: 'req-2',
    timestamp: '14:01:40',
    keyName: 'support-bot',
    modelServed: 'Groq Llama',
    latencyFormatted: '310 ms',
    isRejected: false,
    outcomeText: 'Served by Groq Llama in 310 ms',
    candidates: [],
  },
  {
    id: 'req-3',
    timestamp: '13:59:12',
    keyName: 'notebook',
    modelServed: 'Rejected',
    latencyFormatted: '12 ms',
    isRejected: true,
    outcomeText: 'Needs image input. This key allows text only.',
    candidates: [],
  },
];

const mockProviderHealth = [
  {
    id: 'google',
    name: 'Google Gemini',
    isCoolingDown: true,
    cooldownSeconds: 38,
    modelsCount: 14,
    connectedKeys: '1 key',
    medianLatency: '620 ms',
    latencyHistory: [5, 6, 5, 7, 6, 8, 6, 5],
    quotaPercent: 62,
    confirmedByProvider: true,
  },
  {
    id: 'groq',
    name: 'Groq',
    isCoolingDown: false,
    cooldownSeconds: 0,
    modelsCount: 9,
    connectedKeys: '2 keys',
    medianLatency: '310 ms',
    latencyHistory: [4, 3, 4, 3, 3, 4, 3, 3],
    quotaPercent: 40,
    confirmedByProvider: true,
  },
];

const mockQuotas = [
  {
    provider: 'Google Gemini',
    scope: 'Model (gemini-2.5-flash)',
    resource: 'Request Rate (RPM)',
    limitFormatted: '15 RPM',
    remainingFormatted: '7 RPM remaining',
    percentUsed: 53,
    resetInfo: 'Resets in 38s',
    confidence: 'Confirmed' as const,
  },
];

const mockCircuits = [
  {
    target: 'Gemini Flash (gemini-2.5-flash)',
    provider: 'Google Gemini',
    state: 'half_open' as const,
    failureCount: 4,
    threshold: 5,
    openDurationSeconds: 30,
    probeInFlight: true,
    description: 'Cooldown expired. 1 recovery probe currently testing upstream response.',
  },
  {
    target: 'Groq Llama (llama-3.3-70b)',
    provider: 'Groq',
    state: 'closed' as const,
    failureCount: 0,
    threshold: 5,
    openDurationSeconds: 30,
    probeInFlight: false,
    description: 'Normal traffic flowing with zero consecutive upstream errors.',
  },
];

const mockEvents = [
  {
    id: 'evt-1',
    timestamp: '14:02:11',
    eventType: 'FAILOVER_SUCCEEDED' as const,
    provider: 'Groq',
    model: 'llama-3.3-70b',
    level: 'Level 3' as const,
    details: 'Served by Groq Llama in 412 ms after Gemini rate limit.',
  },
  {
    id: 'evt-2',
    timestamp: '14:02:11',
    eventType: 'FAILOVER_STARTED' as const,
    provider: 'Google Gemini',
    model: 'gemini-2.5-flash',
    level: 'Level 3' as const,
    details: 'HTTP 429 received. Failing over to Groq Llama (ranked #2).',
  },
  {
    id: 'evt-3',
    timestamp: '14:02:10',
    eventType: 'RATE_LIMIT_DETECTED' as const,
    provider: 'Google Gemini',
    model: 'gemini-2.5-flash',
    details: '429 Rate limited. Cooldown initiated for 38 seconds.',
  },
];

const mockAuditLogs = [
  {
    title: 'Provider key added',
    detail: 'Groq · API key connected and validated',
    timestamp: 'Today, 13:40',
  },
];

describe('Overview Dashboard (Overview.tsx)', () => {
  it('renders time-of-day greeting header and Connect provider button', () => {
    renderWithProviders(
      <Overview
        initialSummary={mockOverviewSummary}
        initialReliability={mockReliabilitySummary}
        initialFeed={mockLiveFeed}
        initialHourlyBars={mockHourlyBars}
        initialPinkHours={[14]}
      />
    );

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: /Good (morning|afternoon|evening)/i,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/running/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /Connect provider/i })
    ).toBeInTheDocument();
  });

  it('renders 4 KPI cards with metrics and sparklines', () => {
    renderWithProviders(
      <Overview
        initialSummary={mockOverviewSummary}
        initialReliability={mockReliabilitySummary}
        initialFeed={mockLiveFeed}
        initialHourlyBars={mockHourlyBars}
      />
    );

    const kpiGrid = screen.getByTestId('kpi-grid');
    expect(within(kpiGrid).getByText('Requests')).toBeInTheDocument();
    expect(within(kpiGrid).getByText('48,210')).toBeInTheDocument();

    expect(within(kpiGrid).getByText('Success rate')).toBeInTheDocument();
    expect(within(kpiGrid).getByText('99.8%')).toBeInTheDocument();

    expect(within(kpiGrid).getByText('Median latency')).toBeInTheDocument();
    expect(within(kpiGrid).getByText('412 ms')).toBeInTheDocument();

    expect(within(kpiGrid).getByText('Failovers')).toBeInTheDocument();
    expect(within(kpiGrid).getByText('93')).toBeInTheDocument();
  });

  it('renders 24-hour requests per hour bar chart with pink 429 indicators', () => {
    renderWithProviders(
      <Overview
        initialSummary={mockOverviewSummary}
        initialReliability={mockReliabilitySummary}
        initialFeed={mockLiveFeed}
        initialHourlyBars={mockHourlyBars}
        initialPinkHours={[14]}
      />
    );

    expect(
      screen.getByRole('heading', { level: 2, name: /Requests per hour/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Pink hours had rate-limit events/i)
    ).toBeInTheDocument();

    const hourlyBars = screen.getByTestId('hourly-bars');
    expect(hourlyBars).toBeInTheDocument();
    expect(hourlyBars.children.length).toBe(24);
  });

  it('renders live requests streaming feed with entries', () => {
    renderWithProviders(
      <Overview
        initialSummary={mockOverviewSummary}
        initialReliability={mockReliabilitySummary}
        initialFeed={mockLiveFeed}
        initialHourlyBars={mockHourlyBars}
      />
    );

    expect(
      screen.getByRole('heading', { level: 2, name: /Live requests/i })
    ).toBeInTheDocument();
    expect(screen.getByTestId('live-feed')).toBeInTheDocument();
    expect(screen.getAllByText(/Groq Llama/i).length).toBeGreaterThan(0);
  });
});

describe('Request Explorer (RequestExplorer.tsx & components/requests/)', () => {
  it('renders 340px split layout with request list and detailed inspection', () => {
    renderWithProviders(<RequestExplorer initialRequests={mockRequests} />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Requests' })
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Search requests/i)).toBeInTheDocument();
    expect(screen.getByTestId('request-row-0')).toBeInTheDocument();
    expect(screen.getByTestId('request-detail')).toBeInTheDocument();
  });

  it('renders candidate evaluation breakdown tree with status dots and score bars', () => {
    renderWithProviders(<RequestExplorer initialRequests={mockRequests} />);

    const candTree = screen.getByTestId('candidate-tree');
    expect(candTree).toBeInTheDocument();
    expect(within(candTree).getByText('Candidate Evaluation')).toBeInTheDocument();

    // First request is support-bot served by Groq Llama with Gemini Flash rate limited
    expect(
      screen.getByText(/Served by Groq Llama in 412 ms/i)
    ).toBeInTheDocument();
    expect(within(candTree).getByText('Selected')).toBeInTheDocument();
    expect(within(candTree).getAllByText('Skipped').length).toBeGreaterThan(0);
    expect(
      within(candTree).getByText(/Rate limited\. Cooling down/i)
    ).toBeInTheDocument();
  });

  it('switches inspected request when selecting a different row', () => {
    renderWithProviders(<RequestExplorer initialRequests={mockRequests} />);

    // Click request row 3 (notebook rejected)
    const row3 = screen.getByTestId('request-row-3');
    fireEvent.click(row3);

    expect(
      screen.getAllByText(/Needs image input\. This key allows text only/i).length
    ).toBeGreaterThan(0);
    const detail = screen.getByTestId('request-detail');
    expect(within(detail).getByText('Rejected')).toBeInTheDocument();
  });

  it('filters requests by search input query', () => {
    renderWithProviders(<RequestExplorer initialRequests={mockRequests} />);

    const searchInput = screen.getByPlaceholderText(/Search requests/i);
    fireEvent.change(searchInput, { target: { value: 'research-agent' } });

    expect(screen.getAllByText('research-agent').length).toBeGreaterThan(0);
    expect(screen.queryByText('14:01:40')).not.toBeInTheDocument();
  });
});

describe('Usage & Analytics (Analytics.tsx & components/analytics/)', () => {
  it('renders KPI metrics and VolumeTrends chart with timeframe selection', () => {
    renderWithProviders(<Analytics />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Analytics' })
    ).toBeInTheDocument();
    expect(screen.getByTestId('volume-trends-card')).toBeInTheDocument();

    const tf24h = screen.getByRole('button', { name: '24H' });
    fireEvent.click(tf24h);
    expect(tf24h).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders TokenMetrics component with input and output token consumption', () => {
    renderWithProviders(
      <TokenMetrics
        inputTokens={14200000}
        outputTokens={7200000}
        totalTokens={21400000}
        totalRequests={48210}
      />
    );

    expect(screen.getByTestId('token-metrics-card')).toBeInTheDocument();
    expect(screen.getByText(/14\.2M/i)).toBeInTheDocument();
    expect(screen.getByText(/7\.2M/i)).toBeInTheDocument();
    expect(screen.getByText('444')).toBeInTheDocument();
  });

  it('renders CostBreakdown showing provider shares and model table', () => {
    renderWithProviders(
      <CostBreakdown
        initialShares={[
          { name: 'Groq', sharePercent: 38 },
          { name: 'Google Gemini', sharePercent: 29 },
        ]}
        savingsFormatted="$28.40 saved"
      />
    );

    expect(screen.getByTestId('cost-breakdown-section')).toBeInTheDocument();
    expect(screen.getAllByText('Groq').length).toBeGreaterThan(0);
    expect(screen.getByText('38%')).toBeInTheDocument();
    expect(screen.getAllByText('Google Gemini').length).toBeGreaterThan(0);
    expect(screen.getByText('29%')).toBeInTheDocument();
    expect(screen.getByText('$28.40 saved')).toBeInTheDocument();
  });
});

describe('Reliability Dashboard (Reliability.tsx & components/reliability/)', () => {
  it('renders top reliability KPIs and ProviderHealthMatrix with cooldown banner', () => {
    renderWithProviders(
      <Reliability
        initialSummary={{
          uptime_percent: 99.98,
          failover_success_rate: 99.98,
          failover_success_count: 93,
          active_cooldowns_count: 1,
          open_circuits_count: 0,
          total_requests: 48210,
        }}
      />
    );

    expect(
      screen.getByRole('heading', { level: 1, name: /Reliability & Failover/i })
    ).toBeInTheDocument();
    expect(screen.getByTestId('reliability-kpi-grid')).toBeInTheDocument();
    expect(screen.getByText('100.0%')).toBeInTheDocument();
  });

  it('renders ProviderHealthMatrix with cooldown banner', () => {
    renderWithProviders(
      <ProviderHealthMatrix initialProviders={mockProviderHealth} />
    );

    const matrix = screen.getByTestId('provider-health-matrix');
    expect(matrix).toBeInTheDocument();
    expect(screen.getByTestId('cooldown-banner-google')).toBeInTheDocument();
    expect(within(matrix).getByText(/Rate limited\./i)).toBeInTheDocument();
  });

  it('renders QuotaGauges with quota capacity and confirmed headers', () => {
    renderWithProviders(<QuotaGauges initialQuotas={mockQuotas} />);

    expect(screen.getByTestId('quota-gauges-card')).toBeInTheDocument();
    expect(screen.getAllByText(/Request Rate \(RPM\)/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/15 RPM/i)).toBeInTheDocument();
    expect(screen.getAllByText('Confirmed').length).toBeGreaterThan(0);
  });

  it('renders CircuitBreakers showing Closed and Half-Open states', () => {
    renderWithProviders(<CircuitBreakers initialCircuits={mockCircuits} />);

    expect(screen.getByTestId('circuit-breakers-card')).toBeInTheDocument();
    expect(screen.getByText(/Half-Open \(Testing\)/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Closed \(Normal\)/i).length).toBeGreaterThan(0);
  });

  it('renders FailoverEventsTable with filter chips and event types', () => {
    renderWithProviders(<FailoverEventsTable initialEvents={mockEvents} />);

    expect(screen.getByTestId('failover-events-card')).toBeInTheDocument();
    expect(screen.getAllByText('Failover Succeeded').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Level 3').length).toBeGreaterThan(0);

    const rateLimitsFilter = screen.getByRole('button', { name: 'Rate Limits' });
    fireEvent.click(rateLimitsFilter);
    expect(screen.getByText(/429 Rate limited/i)).toBeInTheDocument();
  });
});

describe('Settings Screen (Settings.tsx)', () => {
  it('renders account email, rate limit selector, and security audit log', () => {
    renderWithProviders(<Settings initialAuditLogs={mockAuditLogs} />);

    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByDisplayValue(/admin@gateway.local|alex@studio.dev/i)).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Gateway rate limit/i })).toBeInTheDocument();
    expect(screen.getByTestId('audit-log-list')).toBeInTheDocument();
    expect(screen.getAllByText(/Provider key added/i).length).toBeGreaterThan(0);
  });

  it('opens confirmation modal when clicking Delete my data', () => {
    renderWithProviders(<Settings initialAuditLogs={mockAuditLogs} />);

    const deleteBtn = screen.getByRole('button', { name: /Delete my data/i });
    fireEvent.click(deleteBtn);

    expect(screen.getByText(/Delete account & gateway data\?/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Confirm deletion/i })).toBeInTheDocument();
  });
});

describe('Developer Docs (Docs.tsx)', () => {
  it('renders code snippets and switches language tabs', () => {
    renderWithProviders(<Docs />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'Developer Documentation' })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Change the URL\. Keep your existing code\./i)
    ).toBeInTheDocument();

    // Default python snippet
    expect(screen.getByText(/from openai import OpenAI/i)).toBeInTheDocument();

    // Click cURL tab
    const curlTab = screen.getByRole('tab', { name: 'cURL' });
    fireEvent.click(curlTab);
    expect(
      screen.getByText(/curl -X POST http:\/\/localhost:8000\/v1\/chat\/completions/i)
    ).toBeInTheDocument();

    // Click Node.js tab
    const nodeTab = screen.getByRole('tab', { name: 'Node.js' });
    fireEvent.click(nodeTab);
    expect(screen.getByText(/import OpenAI from "openai"/i)).toBeInTheDocument();
  });

  it('renders API endpoints and copy snippet button', () => {
    renderWithProviders(<Docs />);

    expect(screen.getAllByText(/\/v1\/chat\/completions/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\/v1\/models/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId('copy-code-btn')).toBeInTheDocument();
  });
});
