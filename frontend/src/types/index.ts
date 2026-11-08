/**
 * Core Domain & API Types for Relay Gateway
 */

export type ModalityCapability = 'text' | 'image' | 'audio' | 'video' | 'tools' | 'json';

export type ModelAccessType =
  | 'All models'
  | 'Text only'
  | 'Text + Image'
  | 'Text + Audio'
  | 'Text + Video'
  | 'All modalities';

export type RoutingStrategy = 'balanced' | 'quality' | 'speed' | 'custom';

export interface RoutingWeights {
  q: number; // quality
  s: number; // speed
  a: number; // availability
}

export type HealthStatus =
  | 'healthy'
  | 'degraded'
  | 'rate_limited'
  | 'cooling_down'
  | 'auth_failed'
  | 'permission_denied'
  | 'temporarily_unavailable'
  | 'disabled'
  | 'unknown';

export interface User {
  id: string;
  email: string;
  fullName?: string;
  avatarUrl?: string;
}

export interface ProviderCredential {
  id: string;
  provider: 'google' | 'groq' | 'cerebras' | 'openrouter';
  name: string;
  isHealthy: boolean;
  modelCount: number;
  medianLatencyMs: number;
  connectedKeysCount: number;
  quotaUsedPercent: number;
  latencyHistory: number[];
  cooldownSecondsRemaining?: number;
  cooldownConfirmed?: boolean;
}

export interface UnifiedModel {
  id: string;
  name: string;
  contextWindow: string;
  capabilities: string[];
  routes: Array<{
    provider: string;
    isAvailable: boolean;
    latencyMs?: number;
  }>;
}

export interface VirtualAPIKey {
  id: string;
  name: string;
  keyPrefix: string;
  fullKeyRevealed?: string;
  strategy: string;
  modelAccess: ModelAccessType;
  dailyLimit: number;
  dailyUsagePercent: number;
  expiresAt: string;
  weights: RoutingWeights;
  isActive: boolean;
}

export interface CandidateBreakdownItem {
  modelName: string;
  status: 's' | 'x' | 'o' | 'selected' | 'skipped' | 'rate_limited' | 'eligible';
  reason?: string;
  statusDetails?: string;
  score?: number;
  scoreFormatted?: string;
  providerName?: string;
  latencyMs?: number;
  costEstimate?: string;
}

export interface RequestLogItem {
  id: string;
  timestamp: string;
  keyName: string;
  modelServed: string;
  latencyFormatted: string;
  isRejected: boolean;
  outcomeText: string;
  candidates: CandidateBreakdownItem[];
}

export interface QuotaInfo {
  provider: string;
  quotaScope: string;
  resourceType: string;
  limit: number;
  remaining: number;
  resetAt?: string;
  retryAfter?: number;
  confidence: 'Confirmed' | 'Estimated' | 'Unknown';
}

export interface ReliabilitySummary {
  requestsTotal: number;
  successRate: number;
  medianLatencyMs: number;
  failoversTotal: number;
  cooldownActiveCount: number;
}
