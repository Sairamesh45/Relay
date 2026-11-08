import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api, setAuthToken, setDevUser } from '../src/api/client';

describe('API Client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAuthToken(null);
    setDevUser('dev-user-alex-relay', 'alex@studio.dev');
  });

  it('injects Dev Auth headers when no token is present', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: 'ok' }),
    });
    global.fetch = mockFetch;

    await api.get('/health');

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('X-Dev-User-Id')).toBe('dev-user-alex-relay');
    expect(headers.get('X-Dev-User-Email')).toBe('alex@studio.dev');
  });

  it('injects Bearer token when auth token is set', async () => {
    setAuthToken('test-supabase-jwt-12345');

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: 'key-1' }],
    });
    global.fetch = mockFetch;

    await api.keys.list();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.get('Authorization')).toBe('Bearer test-supabase-jwt-12345');
    expect(headers.get('X-Dev-User-Id')).toBeNull();
  });
});
