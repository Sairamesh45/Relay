/**
 * Typed API Client for Relay Unified Gateway
 * Connects to FastAPI backend at /api/v1
 * Supports Bearer token injection and Dev Auth headers fallback.
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

let authToken: string | null = null;
let devUserId: string | null = null;
let devUserEmail: string | null = null;

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function setDevUser(id: string | null, email: string | null) {
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

export async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit & { _isRetry?: boolean } = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

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
      return apiRequest<T>(endpoint, { ...options, _isRetry: true });
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

  return response.json();
}

export const api = {
  get: <T = any>(endpoint: string, options?: RequestInit) =>
    apiRequest<T>(endpoint, { ...options, method: 'GET' }),

  post: <T = any>(endpoint: string, data?: unknown, options?: RequestInit) =>
    apiRequest<T>(endpoint, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    }),

  put: <T = any>(endpoint: string, data?: unknown, options?: RequestInit) =>
    apiRequest<T>(endpoint, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    }),

  delete: <T = any>(endpoint: string, options?: RequestInit) =>
    apiRequest<T>(endpoint, { ...options, method: 'DELETE' }),

  auth: {
    me: () => api.get('/auth/me'),
    email: (email: string, full_name?: string) =>
      api.post('/auth/email', { email, full_name }),
    google: (idToken: string) => api.post('/auth/google', { id_token: idToken }),
    refresh: () => api.post('/auth/refresh'),
    logout: () => api.post('/auth/logout'),
  },

  // Domain endpoint helpers
  providers: {
    list: () => api.get('/providers'),
    credentials: () => api.get('/providers/credentials'),
    connect: (provider: string, apiKey: string) =>
      api.post(`/providers/${provider}/credentials`, { api_key: apiKey }),
    deleteCredential: (id: string) =>
      api.delete(`/providers/credentials/${id}`),
    validate: (id: string) =>
      api.post(`/providers/credentials/${id}/validate`),
    syncModels: (credentialId?: string) =>
      api.post(credentialId ? `/providers/credentials/${credentialId}/models` : '/models/sync'),
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
    sync: () => api.post('/models/sync'),
  },

  keys: {
    list: () => api.get('/keys'),
    get: (id: string) => api.get(`/keys/${id}`),
    create: (data: {
      name: string;
      model_access?: string;
      daily_limit?: number;
      routing_strategy?: string;
    }) => api.post('/keys', data),
    revoke: (id: string) => api.delete(`/keys/${id}`),
    rotate: (id: string) => api.post(`/keys/${id}/rotate`),
    getRouting: (id: string) => api.get(`/keys/${id}/routing`),
    updateRouting: (id: string, policy: any) => api.put(`/keys/${id}/routing`, policy),
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
