# Project: Relay — One API. Every model.

## Architecture
Relay connects AI providers (Google Gemini, Groq, OpenRouter) into a unified, reliable, OpenAI-compatible gateway with intelligent routing, capability filtering, quota tracking, automatic failover, and a high-fidelity glassmorphism management dashboard.

### Subsystems:
1. **Core Gateway & Routing (Phases 1–5)**: FastAPI service authenticating virtual API keys, discovering user models, applying routing presets/policies, and logging requests.
2. **Reliability & Execution Engine (Phase 6)**: Multi-attempt failover execution, 13-category error classification, quota tracking, credential health state machines, cooldown manager, circuit breakers, and pre/post-first-chunk streaming semantics.
3. **Frontend Application (Phase 7)**: React 18 + TypeScript + Vite + Tailwind CSS dashboard strictly adhering to `c:\Users\hi\Downloads\relay.html` (Urbanist + Hanken Grotesk, Marshmallow White, Galactic Violet, Bubblegum Pink, 22px cards, 24px drawers, glassmorphism).
4. **E2E Testing Track (Dual Track)**: Requirement-driven, opaque-box test suites (Tiers 1–4) and adversarial coverage hardening (Tier 5).

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Database Schema & Alembic Migration | Add `CredentialHealth`, `QuotaState`, `CircuitBreakerState`, `ReliabilityEvent` in single migration branching from `4f17b2d73118` | M1 | Survey (Explorer 1) |
| 2 | Phase 5 Routing Compatibility Layer | Add non-breaking `get_ranked_candidates(db, ctx)` method to `RoutingEngine` | M1 | Survey (Explorer 1, 3) |
| 3 | 13-Category Error Classification | Normalize provider errors across Gemini, Groq, OpenRouter into canonical categories | M2 | Survey (Explorer 3) |
| 4 | Quota Detection & State Tracking | Parse rate-limit/quota headers, model/org scopes, track remaining capacity & reset times | M2 | Survey (Explorer 3) |
| 5 | Credential Health State Machine | 9 states (`healthy`, `cooling_down`, `rate_limited`, `auth_failed`, etc.) with non-auto-recovering auth failure | M2 | Survey (Explorer 3) |
| 6 | Cooldown Manager with Backoff & Jitter | Scope-aware (model vs credential) cooldowns, provider reset time respect, failure counter reset | M2 | Survey (Explorer 3) |
| 7 | Circuit Breaker Engine | Closed/Open/Half-Open state transitions, observation windows, half-open request probe concurrency limit | M3 | Survey (Explorer 3) |
| 8 | Retry Policy & Budget Enforcer | Enforce `max_attempts`, `max_failover_candidates`, total request deadline, per-attempt timeout | M3 | Survey (Explorer 3) |
| 9 | 3-Level Automatic Failover Engine | Level 1 (same model, diff key), Level 2 (compatible model, same provider), Level 3 (compatible model, diff provider) | M3 | Survey (Explorer 3) |
| 10 | Streaming Failure Semantics | Safe pre-first-chunk retry/failover vs terminal normalized SSE error event post-chunk 1 | M3 | Survey (Explorer 3) |
| 11 | Reliability Event Logging | Structured audit recording for cooldowns, circuit trips, failover initiations, recovery events | M3 | Survey (Explorer 3) |
| 12 | Phase 6 REST API Endpoints | 7 endpoints: `/api/v1/health/providers`, `/api/v1/providers/credentials/health`, `/api/v1/quotas`, `/api/v1/reliability/*` | M1, M2, M3 | Survey (Explorer 1, 3) |
| 13 | Frontend Foundation & Design Tokens | Setup Vite + TS + Tailwind in `frontend/`, configure exact fonts, colors, glassmorphism, 22px cards, AppLayout shell | M4 | Survey (Explorer 2) |
| 14 | Authentication Shell & Google OAuth | Supabase Auth Google OAuth + dev fallback (`X-Dev-User-Id`), split art panel screen | M4 | Survey (Explorer 2) |
| 15 | Public Landing Page | Full showcase from `relay.html` `#landing`: live interactive routing simulator, SDK code block, feature sections | M4 | Survey (Explorer 2) |
| 16 | Providers View & Connect Drawer | Provider cards, quota donut gauges, latency sparklines, cooldown countdown timers, connect drawer | M5 | Survey (Explorer 2) |
| 17 | Unified Models Catalog | Model table, search, capability filter chips (`Text`, `Tools`, `Image`), route health dots | M5 | Survey (Explorer 2) |
| 18 | Virtual Keys & Routing Policy Editor | Key cards, daily quota bars, create key drawer, routing policy editor drawer with live candidate ranking preview | M5 | Survey (Explorer 2) |
| 19 | Overview Dashboard | 4 KPI cards with SVG sparklines, 24h hourly request bar chart (pink 429 bars), live requests feed | M6 | Survey (Explorer 2) |
| 20 | Request Explorer & Candidate Breakdown | 340px split list + detail drawer with candidate scoring tree (`dot.s`, `dot.x`, `dot`, score progress bars) | M6 | Survey (Explorer 2) |
| 21 | Reliability Dashboard & Quotas | Phase 6 health matrix, quota utilization gauges, circuit breaker states, and chronological failover event table | M6 | Survey (Explorer 2) |
| 22 | Settings, Audit Log & Developer Docs | RPM limit setting, account deletion, security audit log, interactive OpenAI SDK documentation | M6 | Survey (Explorer 2) |
| 23 | E2E Testing Suite (Tiers 1–4) | Independent opaque-box test suite covering feature, boundary, pairwise combination, and real-world workloads | M7 | Survey (Dual Track) |
| 24 | Final Integration & Adversarial Verification | 100% E2E test pass, adversarial coverage hardening (Tier 5), forensic integrity verification | M8 | Survey (Final Milestone) |

---

## Milestones
| # | Name | Scope | Dependencies | Status | Owner |
|---|------|-------|-------------|--------|-------|
| M1 | Database Coordination & Compatibility Layer | 4 new SQLAlchemy models, single linear Alembic migration branching from `4f17b2d73118`, `RoutingEngine.get_ranked_candidates()` | none | DONE | Agent 0 (Technical Lead) |
| M2 | Provider Health, Quota & Cooldown Engine | 13-category error classification, quota tracking, credential health state machine, cooldown manager, Health/Quota REST APIs | M1 | DONE | Agent 1 |
| M3 | Retry, Failover & Execution Engine | Circuit breakers, retry policies/budgets, 3-level failover engine, pre/post-chunk streaming semantics, Gateway integration, Reliability APIs | M1, M2 | IN_PROGRESS | Agent 2 |
| M4 | Frontend Foundation, Design System & Landing Page | Vite + React + TS setup in `frontend/`, exact `relay.html` design tokens, glassmorphism, AppLayout shell, Auth split-screen, Landing Page | none | DONE | Agent 3 |
| M5 | Core Product Screens & Routing Editor | Providers view, Connect Drawer, Models catalog, Virtual Keys view, Create Key Drawer, Routing Policy Editor with live ranking preview | M4 | DONE | Agent 4 |
| M6 | Observability, Request Explorer & Settings | Overview KPIs with 24h bar chart, Request Explorer split view with candidate scoring tree, Reliability dashboard, Settings & Developer docs | M4 | DONE | Agent 5 |
| M7 | E2E Testing Suite (Tiers 1–4) | Requirement-driven opaque-box test harness, runner, and test cases covering all 24 inventory features, publish `TEST_READY.md` | none | DONE | E2E Test Orchestrator |
| M8 | Final Integration, E2E Pass & Adversarial Hardening | End-to-end integration, 100% E2E test pass, Tier 5 adversarial testing, Forensic Integrity Audit | M1–M7 | PLANNED | Technical Lead & Orchestrator |

---

## Interface Contracts

### 1. Database & Models (Agent 0 ↔ Agent 1, Agent 2)
- Models registered in `backend/app/models/`:
  - `CredentialHealth`: `credential_id (FK)`, `health_status (Enum)`, `failure_count (int)`, `consecutive_failures (int)`, `last_success_at`, `last_failure_at`, `cooldown_until`, `last_error_category (str)`, `error_details (JSONB)`
  - `QuotaState`: `credential_id (FK, nullable)`, `provider (str)`, `quota_scope (str)`, `resource_type (str)`, `limit (bigint)`, `remaining (bigint)`, `reset_at`, `retry_after (int)`, `confidence (str)`, `source (str)`, `observed_at`
  - `CircuitBreakerState`: `scope_type (str)`, `scope_id (str)`, `state (Enum: closed, open, half_open)`, `failure_count (int)`, `success_count (int)`, `last_state_change`, `probe_requests_in_flight (int)`
  - `ReliabilityEvent`: `id (UUID)`, `timestamp`, `event_type (str)`, `provider (str)`, `credential_id (FK)`, `model_id (str)`, `metadata (JSONB)`
- Alembic Migration: Single linear revision script `b7a8ff66e01a_create_phase6_reliability_tables.py` with `down_revision = "4f17b2d73118"`.

### 2. Routing Compatibility (Agent 0 ↔ Agent 2)
- Signature:
  ```python
  async def get_ranked_candidates(
      self,
      db: AsyncSession,
      ctx: CandidateDiscoveryContext,
  ) -> list[ScoredCandidate]:
      """Discovers eligible candidates, scores them, and returns full ranked list without side effects."""
  ```

### 3. Error Classification & Provider Adapters (Agent 1 ↔ Agent 2)
- Canonical Categories:
  `RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, `SERVER_ERROR`, `NETWORK_ERROR`, `TIMEOUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `MODEL_UNAVAILABLE`, `UNSUPPORTED_PARAMETER`, `CONTEXT_LENGTH_EXCEEDED`, `QUOTA_EXHAUSTED`, `CONTENT_REJECTED`, `UNKNOWN`.
- Classification Function:
  ```python
  def classify_provider_error(error: Exception, provider: str, status_code: int | None = None, response_headers: dict | None = None) -> ClassifiedError:
      ...
  ```

### 4. Failover & Execution Engine (Agent 2 ↔ ChatGatewayService)
- Signature:
  ```python
  class RequestExecutionEngine:
      async def execute_chat_completion(
          self, db: AsyncSession, user: User, key: VirtualAPIKey, request: ChatCompletionRequest, request_id: str
      ) -> tuple[ChatCompletionResponse, ExecutionTrace]:
          ...
      async def execute_stream_completion(
          self, db: AsyncSession, user: User, key: VirtualAPIKey, request: ChatCompletionRequest, request_id: str
      ) -> AsyncGenerator[str, None]:
          ...
  ```

### 5. Backend ↔ Frontend API Contracts
- REST Endpoints for Frontend:
  - Providers: `GET /api/v1/providers`, `POST /api/v1/providers/{p}/credentials`, `GET /api/v1/providers/credentials`, `DELETE /api/v1/providers/credentials/{id}`, `POST /api/v1/providers/credentials/{id}/validate`
  - Models: `GET /api/v1/models`, `POST /api/v1/models/sync`
  - Virtual Keys: `POST /api/v1/keys`, `GET /api/v1/keys`, `GET /api/v1/keys/{id}`, `DELETE /api/v1/keys/{id}`, `POST /api/v1/keys/{id}/rotate`
  - Routing: `GET /api/v1/keys/{id}/routing`, `PUT /api/v1/keys/{id}/routing`, `POST /api/v1/keys/{id}/routing/preview`, `GET /api/v1/routing/presets`
  - Usage & Request Explorer: `GET /api/v1/usage/summary`, `GET /api/v1/usage/requests`, `GET /api/v1/usage/requests/{request_id}` (including candidate evaluation breakdown)
  - Reliability: `GET /api/v1/health/providers`, `GET /api/v1/providers/credentials/health`, `GET /api/v1/quotas`, `GET /api/v1/reliability/events`, `GET /api/v1/reliability/summary`

---

## Code Layout & File Ownership
Strict boundary enforcement: Concurrent workers MUST NOT write to the same files.

| Agent | Role | Exclusive Write Paths |
|---|---|---|
| **Agent 0** | Technical Lead | `backend/app/models/reliability.py`, `backend/alembic/versions/*_phase6*.py`, `backend/app/services/routing/engine.py` (compatibility layer), `backend/app/api/routes/__init__.py`, integration tests |
| **Agent 1** | Provider Health & Quota | `backend/app/services/reliability/error_classifier.py`, `backend/app/services/reliability/health_service.py`, `backend/app/services/reliability/quota_service.py`, `backend/app/services/reliability/cooldown_manager.py`, `backend/app/api/routes/reliability_health.py` |
| **Agent 2** | Failover & Execution | `backend/app/services/reliability/circuit_breaker.py`, `backend/app/services/reliability/retry_policy.py`, `backend/app/services/reliability/failover_engine.py`, `backend/app/services/chat_gateway.py`, `backend/app/api/routes/reliability_events.py` |
| **Agent 3** | Frontend Foundation & Shell | `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/src/tokens/*`, `frontend/src/components/layout/*`, `frontend/src/components/ui/*`, `frontend/src/pages/Landing.tsx`, `frontend/src/pages/Auth.tsx`, `frontend/src/api/client.ts` |
| **Agent 4** | Core Product Screens | `frontend/src/pages/Providers.tsx`, `frontend/src/pages/Models.tsx`, `frontend/src/pages/Keys.tsx`, `frontend/src/components/providers/*`, `frontend/src/components/models/*`, `frontend/src/components/keys/*`, `frontend/src/components/routing/*` |
| **Agent 5** | Observability & Account | `frontend/src/pages/Overview.tsx`, `frontend/src/pages/RequestExplorer.tsx`, `frontend/src/pages/Analytics.tsx`, `frontend/src/pages/Reliability.tsx`, `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Docs.tsx`, `frontend/src/components/requests/*`, `frontend/src/components/analytics/*` |
| **E2E Tester**| E2E Testing Track | `tests/e2e/*`, `TEST_INFRA.md`, `TEST_READY.md` |
