import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  api,
  setAuthToken,
  setDevUser,
  invalidateCache,
  clearCache,
  apiCache,
  inFlightRequests,
} from '../src/api/client';

describe('API Client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    clearCache();
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

  describe('In-flight Request Deduplication', () => {
    it('shares a single network fetch between concurrent identical GET requests', async () => {
      let resolveFetch!: (val: any) => void;
      const pendingFetch = new Promise((resolve) => {
        resolveFetch = resolve;
      });

      const mockFetch = vi.fn().mockImplementation(() => pendingFetch);
      global.fetch = mockFetch;

      // Dispatch two concurrent identical calls
      const promise1 = api.models.list();
      const promise2 = api.models.list();

      // Ensure inFlightRequests is tracking the pending request
      expect(inFlightRequests.size).toBe(1);

      // Resolve the single network call
      resolveFetch({
        ok: true,
        status: 200,
        json: async () => [{ id: 'gemini-flash', name: 'Gemini Flash' }],
      });

      const [res1, res2] = await Promise.all([promise1, promise2]);

      // Assert fetch was dispatched exactly once
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(res1).toEqual([{ id: 'gemini-flash', name: 'Gemini Flash' }]);
      expect(res2).toEqual([{ id: 'gemini-flash', name: 'Gemini Flash' }]);

      // In-flight map is cleaned up after settlement
      expect(inFlightRequests.size).toBe(0);
    });
  });

  describe('Categorized In-Memory Caching & Stale-While-Revalidate', () => {
    it('returns cached data within the stale window without calling fetch again', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [{ id: 'model-1', name: 'Llama 3.3 70B' }],
      });
      global.fetch = mockFetch;

      // First call executes network fetch and populates cache
      const first = await api.models.list();
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(first).toEqual([{ id: 'model-1', name: 'Llama 3.3 70B' }]);

      // Check apiCache entry exists with proper timestamps
      const cacheKey = 'GET:/models?limit=500';
      const entry = apiCache.get(cacheKey);
      expect(entry).toBeDefined();
      expect(entry?.data).toEqual([{ id: 'model-1', name: 'Llama 3.3 70B' }]);
      expect(entry?.staleAt).toBeGreaterThan(Date.now());
      expect(entry?.expiresAt).toBeGreaterThan(entry!.staleAt);

      // Second call within stale window resolves from cache immediately
      const second = await api.models.list();
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(second).toEqual(first);
    });

    it('invalidates cache when invalidateCache is called with matching endpoint prefix', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [{ id: 'key-1' }],
      });
      global.fetch = mockFetch;

      await api.keys.list();
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Invalidate /keys prefix
      invalidateCache('/keys');
      expect(apiCache.get('GET:/keys')).toBeUndefined();

      // Next call triggers fetch again
      await api.keys.list();
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('invalidates relevant cache categories upon provider and model mutations', async () => {
      const mockFetch = vi.fn().mockImplementation((_url: string, options?: any) => {
        if (options?.method === 'POST' || options?.method === 'DELETE') {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ success: true }),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [{ id: 'data' }],
        });
      });
      global.fetch = mockFetch;

      // Populate /providers and /models cache
      await api.providers.credentials();
      await api.models.list();
      expect(apiCache.size).toBe(2);

      // Provider connect mutation should invalidate /providers, /models, and /reliability
      await api.providers.connect('groq', 'gsk_test123');

      expect(apiCache.get('GET:/providers/credentials')).toBeUndefined();
      expect(apiCache.get('GET:/models?limit=500')).toBeUndefined();

      // Models sync mutation should invalidate /models
      await api.models.list(); // Re-populate
      expect(apiCache.get('GET:/models?limit=500')).toBeDefined();

      await api.models.sync();
      expect(apiCache.get('GET:/models?limit=500')).toBeUndefined();
    });

    it('invalidates keys cache upon virtual key mutations (create, revoke, updateRouting)', async () => {
      const mockFetch = vi.fn().mockImplementation((_url: string, options?: any) => {
        if (options?.method === 'POST' || options?.method === 'DELETE' || options?.method === 'PUT') {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'key-new' }),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [{ id: 'key-1' }],
        });
      });
      global.fetch = mockFetch;

      await api.keys.list();
      expect(apiCache.get('GET:/keys')).toBeDefined();

      // Create virtual key
      await api.keys.create({ name: 'test-bot' });
      expect(apiCache.get('GET:/keys')).toBeUndefined();

      // Re-populate and revoke
      await api.keys.list();
      expect(apiCache.get('GET:/keys')).toBeDefined();
      await api.keys.revoke('key-1');
      expect(apiCache.get('GET:/keys')).toBeUndefined();

      // Re-populate and update routing
      await api.keys.list();
      expect(apiCache.get('GET:/keys')).toBeDefined();
      await api.keys.updateRouting('key-1', { strategy: 'cost' });
      expect(apiCache.get('GET:/keys')).toBeUndefined();
    });

    it('bypasses cache when forceRefresh option is set to true', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ count: 42 }),
      });
      global.fetch = mockFetch;

      await api.usage.summary();
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // Regular call uses cache
      await api.usage.summary();
      expect(mockFetch).toHaveBeenCalledTimes(1);

      // forceRefresh bypasses cache
      await api.get('/usage/summary', { forceRefresh: true });
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('clears all cache and in-flight maps via clearCache', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      });
      global.fetch = mockFetch;

      await api.get('/quotas');
      await api.get('/usage/summary');
      expect(apiCache.size).toBe(2);

      clearCache();
      expect(apiCache.size).toBe(0);
      expect(inFlightRequests.size).toBe(0);
    });
  });
});
