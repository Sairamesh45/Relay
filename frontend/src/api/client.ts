/**
 * Typed API Client for Relay Unified Gateway
 * Connects to FastAPI backend at /api/v1
 * Supports Bearer token injection, Dev Auth headers fallback,
 * in-flight Promise deduplication, and categorized stale-while-revalidate caching.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface CacheEntry<T> {
  data: T;
  timestamp: number;
  staleAt: number;
  expiresAt: number;
}

export interface CacheRule {
  staleTime: number;
  cacheTime: number;
}

// In-flight request deduplication map for concurrent pending GET requests
export const inFlightRequests = new Map<string, Promise<any>>();

// Categorized in-memory data cache
export const apiCache = new Map<string, CacheEntry<any>>();

// Exact TTL and stale-time rules specified in explorer_perf_frontend/handoff.md
export const CACHE_RULES: Array<{ prefix: string; rule: CacheRule }> = [
  // Health states (order matters: more specific path first)
  { prefix: '/providers/credentials/health', rule: { staleTime: 15_000, cacheTime: 120_000 } },
  { prefix: '/providers/credentials', rule: { staleTime: 60_000, cacheTime: 600_000 } },
  { prefix: '/providers', rule: { staleTime: 60_000, cacheTime: 600_000 } },
  { prefix: '/models', rule: { staleTime: 300_000, cacheTime: 900_000 } },
  { prefix: '/keys', rule: { staleTime: 120_000, cacheTime: 600_000 } },
  { prefix: '/routing', rule: { staleTime: 3_600_000, cacheTime: 86_400_000 } },
  { prefix: '/quotas', rule: { staleTime: 30_000, cacheTime: 300_000 } },
  { prefix: '/usage/summary', rule: { staleTime: 20_000, cacheTime: 120_000 } },
  { prefix: '/reliability/summary', rule: { staleTime: 20_000, cacheTime: 120_000 } },
  { prefix: '/usage/requests', rule: { staleTime: 8_000, cacheTime: 60_000 } },
  { prefix: '/reliability/events', rule: { staleTime: 15_000, cacheTime: 60_000 } },
];

export const DEFAULT_CACHE_RULE: CacheRule = { staleTime: 10_000, cacheTime: 60_000 };

export function getCacheRule(endpoint: string): CacheRule {
  const normalized = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  for (const item of CACHE_RULES) {
    if (normalized.startsWith(item.prefix)) {
      return item.rule;
    }
  }
  return DEFAULT_CACHE_RULE;
}

/**
 * Invalidate cache entries matching an endpoint prefix.
 * If endpointPrefix is omitted, clears all cached entries.
 */
export function invalidateCache(endpointPrefix?: string): void {
  if (!endpointPrefix) {
    apiCache.clear();
    return;
  }
  const cleanPrefix = endpointPrefix.startsWith('/') ? endpointPrefix : `/${endpointPrefix}`;
  for (const key of Array.from(apiCache.keys())) {
    if (key.includes(cleanPrefix) || key.includes(endpointPrefix)) {
      apiCache.delete(key);
    }
  }
  for (const key of Array.from(inFlightRequests.keys())) {
    if (key.includes(cleanPrefix) || key.includes(endpointPrefix)) {
      inFlightRequests.delete(key);
    }
  }
}

/**
 * Clears all in-memory cached responses and in-flight request tracking.
 */
export function clearCache(): void {
  apiCache.clear();
  inFlightRequests.clear();
}

let authToken: string | null = null;
let devUserId: string | null = null;
let devUserEmail: string | null = null;

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

export function setAuthToken(token: string | null) {
  if (token !== authToken) {
    clearCache();
  }
  authToken = token;
}

export function setDevUser(id: string | null, email: string | null) {
  if (id !== devUserId || email !== devUserEmail) {
    clearCache();
  }
  devUserId = id;
  devUserEmail = email;
}

async function attemptTokenRefresh(): Promise<boolean> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }
  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export interface ApiRequestOptions extends RequestInit {
  _isRetry?: boolean;
  forceRefresh?: boolean;
}

export async function apiRequest<T = any>(
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const isGet = !options.method || options.method.toUpperCase() === 'GET';
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const cacheKey = `GET:${normalizedEndpoint}`;
  const now = Date.now();

  // 1. In-memory Cache hit check (for GET requests within freshness window)
  if (isGet && !options.forceRefresh) {
    const cached = apiCache.get(cacheKey);
    if (cached && now < cached.staleAt) {
      return cached.data as T;
    }
  }

  // 2. In-flight Promise deduplication (shares identical concurrent pending requests)
  if (isGet && !options.forceRefresh && inFlightRequests.has(cacheKey)) {
    return inFlightRequests.get(cacheKey)! as Promise<T>;
  }

  // 3. Dispatch HTTP request
  const fetchPromise = (async () => {
    try {
      const url = `${BASE_URL}${normalizedEndpoint}`;

      const headers = new Headers(options.headers || {});
      if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json');
      }

      // Inject Authorization Bearer token if present (cookie is primary, header is optional fallback)
      if (authToken) {
        headers.set('Authorization', `Bearer ${authToken}`);
      } else if (devUserId && devUserEmail) {
        headers.set('X-Dev-User-Id', devUserId);
        headers.set('X-Dev-User-Email', devUserEmail);
      }

      const response = await fetch(url, {
        ...options,
        credentials: 'include', // Ensure HttpOnly cookies are always attached
        headers,
      });

      // Handle 401 Unauthorized with token refresh retry
      if (
        response.status === 401 &&
        !endpoint.includes('/auth/') &&
        !options._isRetry
      ) {
        const refreshed = await attemptTokenRefresh();
        if (refreshed) {
          return await apiRequest<T>(endpoint, { ...options, _isRetry: true });
        }
      }

      if (!response.ok) {
        let errorData: any = null;
        try {
          errorData = await response.json();
        } catch {
          errorData = await response.text();
        }
        const message =
          (typeof errorData === 'object' && errorData?.detail) ||
          (typeof errorData === 'object' && errorData?.message) ||
          response.statusText ||
          `Request failed with status ${response.status}`;
        throw new ApiError(message, response.status, errorData);
      }

      if (response.status === 204) {
        return {} as T;
      }

      const result = await response.json();

      // Store in response cache if GET request
      if (isGet) {
        const rule = getCacheRule(normalizedEndpoint);
        const resolvedAt = Date.now();
        apiCache.set(cacheKey, {
          data: result,
          timestamp: resolvedAt,
          staleAt: resolvedAt + rule.staleTime,
          expiresAt: resolvedAt + rule.cacheTime,
        });
      }

      return result;
    } catch (err) {
      // Stale-if-error fallback: if GET failed and we have unexpired cached data, fall back to it
      if (isGet && !options.forceRefresh) {
        const fallback = apiCache.get(cacheKey);
        if (fallback && Date.now() < fallback.expiresAt) {
          return fallback.data as T;
        }
      }
      throw err;
    } finally {
      if (isGet) {
        inFlightRequests.delete(cacheKey);
      }
    }
  })();

  if (isGet && !options.forceRefresh) {
    inFlightRequests.set(cacheKey, fetchPromise);
  }

  return fetchPromise;
}

export const api = {
  get: <T = any>(endpoint: string, options?: ApiRequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'GET' }),

  post: <T = any>(endpoint: string, data?: unknown, options?: ApiRequestOptions) =>
    apiRequest<T>(endpoint, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    }),

  put: <T = any>(endpoint: string, data?: unknown, options?: ApiRequestOptions) =>
    apiRequest<T>(endpoint, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    }),

  delete: <T = any>(endpoint: string, options?: ApiRequestOptions) =>
    apiRequest<T>(endpoint, { ...options, method: 'DELETE' }),

  auth: {
    me: () => api.get('/auth/me'),
    email: (email: string, full_name?: string) =>
      api.post('/auth/email', { email, full_name }),
    google: (idToken: string) => api.post('/auth/google', { id_token: idToken }),
    refresh: () => api.post('/auth/refresh'),
    logout: async () => {
      clearCache();
      return api.post('/auth/logout');
    },
  },

  // Domain endpoint helpers
  providers: {
    list: () => api.get('/providers'),
    credentials: () => api.get('/providers/credentials'),
    connect: async (provider: string, apiKey: string) => {
      const res = await api.post(`/providers/${provider}/credentials`, { api_key: apiKey });
      invalidateCache('/providers');
      invalidateCache('/models');
      invalidateCache('/reliability');
      return res;
    },
    deleteCredential: async (id: string) => {
      const res = await api.delete(`/providers/credentials/${id}`);
      invalidateCache('/providers');
      invalidateCache('/models');
      invalidateCache('/reliability');
      return res;
    },
    validate: async (id: string) => {
      const res = await api.post(`/providers/credentials/${id}/validate`);
      invalidateCache('/providers/credentials');
      return res;
    },
    syncModels: async (credentialId?: string) => {
      const res = await api.post(credentialId ? `/providers/credentials/${credentialId}/models` : '/models/sync');
      invalidateCache('/models');
      return res;
    },
  },

  models: {
    list: (params?: { query?: string; capability?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.query) q.set('q', params.query);
      if (params?.capability) q.set('capability', params.capability);
      q.set('limit', String(params?.limit || 500));
      const queryStr = `?${q.toString()}`;
      return api.get(`/models${queryStr}`);
    },
    sync: async () => {
      const res = await api.post('/models/sync');
      invalidateCache('/models');
      return res;
    },
  },

  keys: {
    list: () => api.get('/keys'),
    get: (id: string) => api.get(`/keys/${id}`),
    create: async (data: {
      name: string;
      model_access?: string;
      daily_limit?: number;
      routing_strategy?: string;
    }) => {
      const res = await api.post('/keys', data);
      invalidateCache('/keys');
      return res;
    },
    revoke: async (id: string) => {
      const res = await api.delete(`/keys/${id}`);
      invalidateCache('/keys');
      return res;
    },
    rotate: async (id: string) => {
      const res = await api.post(`/keys/${id}/rotate`);
      invalidateCache('/keys');
      return res;
    },
    getRouting: (id: string) => api.get(`/keys/${id}/routing`),
    updateRouting: async (id: string, policy: any) => {
      const res = await api.put(`/keys/${id}/routing`, policy);
      invalidateCache('/keys');
      return res;
    },
    previewRouting: (id: string, weights?: any) =>
      api.post(`/keys/${id}/routing/preview`, weights ? { weights } : {}),
  },

  routing: {
    presets: () => api.get('/routing/presets'),
    capabilities: () => api.get('/routing/capabilities'),
  },

  usage: {
    summary: () => api.get('/usage/summary'),
    requests: (params?: { limit?: number; offset?: number }) => {
      const q = new URLSearchParams();
      if (params?.limit) q.set('limit', String(params.limit));
      if (params?.offset) q.set('offset', String(params.offset));
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return api.get(`/usage/requests${queryStr}`);
    },
    requestDetail: (id: string) => api.get(`/usage/requests/${id}`),
  },

  reliability: {
    healthProviders: () => api.get('/health/providers'),
    credentialsHealth: () => api.get('/providers/credentials/health'),
    quotas: () => api.get('/quotas'),
    events: (params?: { limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.limit) q.set('limit', String(params.limit));
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return api.get(`/reliability/events${queryStr}`);
    },
    summary: () => api.get('/reliability/summary'),
  },
};
