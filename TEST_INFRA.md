# TEST INFRASTRUCTURE SPECIFICATION: RELAY E2E TESTING TRACK

## 1. Overview & Test Philosophy
Relay connects multiple AI provider credentials into a unified, high-reliability, OpenAI-compatible gateway with intelligent routing, capability filtering, quota tracking, automatic failover, and a glassmorphism dashboard.

The E2E test harness adheres to an **opaque-box, requirement-driven testing philosophy** derived directly from `ORIGINAL_REQUEST.md` and `PROJECT.md`:
1. **Opaque-Box Execution**: Tests validate observable contracts (HTTP status codes, response schemas, error structures, database states, and frontend asset/token alignments) without coupling to internal private methods.
2. **Deterministic Upstream Simulation**: Upstream AI providers (Google Gemini, Groq, OpenRouter) are simulated using strict HTTP mock transports reproducing standard and degraded responses (HTTP 200, 401, 429 with `Retry-After`, 500, 502, 503, timeouts, and SSE streams).
3. **No Facades / Genuine Verification**: Every test exercises real routing, validation, error classification, quota updates, circuit breaker transitions, and API contracts. No facade mocks that unconditionally return true are permitted.
4. **Progressive Testability & Isolation**: Tests maintain isolated database sessions, distinct user scopes, and clean state resets, enabling parallel or sequential execution across test tiers.

---

## 2. 4-Tier Test Methodology

The testing suite is structured into four distinct, progressive tiers:

### Tier 1: Feature Coverage (Isolation)
- **Objective**: Verify that each of the 24 features defined in `PROJECT.md` functions correctly in isolation under standard conditions.
- **Requirement**: Minimum 5 independent, non-trivial test cases per feature (120+ tests total).
- **Scope**:
  - Backend schema, models, migrations, and routing compatibility.
  - Reliability engine components (classification, quotas, health state machine, cooldowns, circuit breakers, retries, failover, streaming, events, REST endpoints).
  - Frontend foundation, design tokens, typography, glassmorphism, authentication, public landing page, and all administrative screens.
  - Testing harness and integration verifications.

### Tier 2: Boundary & Corner Cases (Stress & Fault Injection)
- **Objective**: Verify resilience at system boundaries and under edge-case conditions.
- **Requirement**: Comprehensive coverage of boundary values, limit violations, and fault states:
  - 429 Rate Limits: Header variations (`Retry-After` in seconds vs HTTP date formats, zero/negative limits, burst exhaustion).
  - Authentication & Keys: Expired keys, deleted keys, invalid HMAC signatures, empty Bearer tokens, malformed headers.
  - Context & Payload Boundaries: Zero-token prompts, context window overflows, maximum output limits, invalid JSON, unsupported parameters.
  - Network & Upstream Faults: Upstream connection timeouts, read timeouts, malformed upstream chunks, mid-stream disconnects.
  - Health & Circuit Boundaries: Transition thresholds (exact failure counts, half-open probe caps, cooldown expiry races).

### Tier 3: Cross-Feature Combinations (Pairwise & Multi-System Interactions)
- **Objective**: Verify that independent subsystems interact predictably without deadlocks, race conditions, or state corruption.
- **Requirement**: Explicit pairwise integration scenarios:
  1. **Streaming + Failover**: Pre-first-chunk retry/failover vs post-first-chunk normalized terminal SSE error event.
  2. **Routing Policy + Quota Exhaustion**: Failover traversal when primary candidate hits quota limits while respecting routing constraints (same model different credential, compatible model same provider, compatible model different provider).
  3. **Circuit Breaker Open + Alternative Candidate Selection**: Immediate exclusion of candidates with OPEN circuit breaker without making network requests.
  4. **Virtual Key Rate Limiting + Credential Pool State**: Virtual key level rate limiting independent of provider credential health.
  5. **Cooldown Expiry + Concurrency Probes**: Half-open circuit transition allowing bounded recovery probes without request storms.
  6. **Multi-Provider Unified Catalog Mapping + Fallback**: Seamless cross-provider translation across Groq, Gemini, and OpenRouter schemas.
  7. **Audit Logging + Failure Cleanups**: Verifying `GatewayRequestLog`, `RoutingDecisionLog`, and `ReliabilityEvent` entries after aborted or failed requests.

### Tier 4: Real-World Application Scenarios (End-to-End Workloads)
- **Objective**: Simulate realistic production workloads and user interaction flows.
- **Requirement**: Realistic end-to-end integration workflows:
  1. **Multi-Turn Chat Conversations**: Long-context conversation threads with alternating user/assistant turns and streaming token delivery.
  2. **High-Concurrency Traffic**: Concurrent requests across multiple virtual keys competing for shared provider pools.
  3. **Cascading Multi-Provider Failover**: Primary provider returns 500 -> Secondary provider returns 429 -> Tertiary provider successfully completes the request.
  4. **Full Lifecycle Administrative Workflow**: Connect provider -> Sync models -> Create virtual key -> Set custom routing policy -> Execute chat completion -> Inspect telemetry in request explorer.
  5. **Reliability Dashboard Real-Time Telemetry**: Real-time aggregation of provider health matrix, quota utilization gauges, and chronological failover event streams.

---

## 3. Feature Inventory to Test Suite Mapping

| Feature # | Feature Name | Tier 1 Tests | Tier 2 Boundaries | Tier 3 Combinations | Tier 4 Workloads |
|---|---|---|---|---|---|
| **F-01** | Database Schema & Alembic Migration | `test_f01_schema_*` | Schema constraints, nullability | Model relations under failover | Persistent audit trace verification |
| **F-02** | Phase 5 Routing Compatibility Layer | `test_f02_routing_compat_*` | Empty candidate discovery | Compatibility with failover traversal | Multi-candidate ranking preview |
| **F-03** | 13-Category Error Classification | `test_f03_error_classification_*` | Unknown status codes, malformed body | Classification driving failover decision | Cascading error normalization |
| **F-04** | Quota Detection & State Tracking | `test_f04_quota_tracking_*` | Missing headers, negative remaining | Quota exhaustion + routing fallback | Quota utilization aggregation |
| **F-05** | Credential Health State Machine | `test_f05_credential_health_*` | Unrecoverable auth failures | Health state affecting candidate scoring | Health matrix real-time status |
| **F-06** | Cooldown Manager with Backoff & Jitter | `test_f06_cooldown_manager_*` | Model vs Credential scope limits | Cooldown expiry + half-open probes | Recovery under active traffic |
| **F-07** | Circuit Breaker Engine | `test_f07_circuit_breaker_*` | Half-open concurrency limit | Circuit open triggering level 2/3 failover | High-concurrency circuit isolation |
| **F-08** | Retry Policy & Budget Enforcer | `test_f08_retry_policy_*` | Total timeout vs attempt timeout | Retry budget exhaustion | Multi-attempt failover execution |
| **F-09** | 3-Level Automatic Failover Engine | `test_f09_failover_engine_*` | Strict model constraint enforcement | Pairwise level 1, 2, 3 transitions | End-to-end 3-tier provider failover |
| **F-10** | Streaming Failure Semantics | `test_f10_streaming_semantics_*` | Immediate stream disconnect | Pre-chunk failover vs post-chunk error | Multi-turn streaming chat |
| **F-11** | Reliability Event Logging | `test_f11_reliability_events_*` | Large metadata payloads, redactions | Event logging during cascading failures | Chronological event table stream |
| **F-12** | Phase 6 REST API Endpoints | `test_f12_rest_api_endpoints_*` | Unauthorized access, invalid IDs | Filtering and pagination boundaries | Full admin & telemetry inspection |
| **F-13** | Frontend Foundation & Design Tokens | `test_f13_frontend_tokens_*` | Token integrity, typography tokens | Design system consistency across components | Application shell layout |
| **F-14** | Authentication Shell & Google OAuth | `test_f14_auth_shell_*` | Missing session, dev auth fallback | Dev auth header propagation | Session restoration workflow |
| **F-15** | Public Landing Page | `test_f15_landing_page_*` | Simulator state boundaries | Code snippet copy, SDK compatibility | Interactive simulator workflow |
| **F-16** | Providers View & Connect Drawer | `test_f16_providers_view_*` | Form validation, invalid keys | Connect drawer + model auto-sync | Provider lifecycle workflow |
| **F-17** | Unified Models Catalog | `test_f17_models_catalog_*` | Capability filter chips, search | Model search with 0 results | Model discovery and mapping |
| **F-18** | Virtual Keys & Routing Policy Editor | `test_f18_keys_and_routing_*` | Key rate limits, budget caps | Policy update + candidate preview | Key creation and chat consumption |
| **F-19** | Overview Dashboard | `test_f19_overview_dashboard_*` | Empty metrics handling, zero values | 24h chart data with 429 pink bars | Full KPI and live request feed |
| **F-20** | Request Explorer & Candidate Breakdown | `test_f20_request_explorer_*` | Missing request ID, pagination | Candidate scoring tree rendering | Request details drill-down |
| **F-21** | Reliability Dashboard & Quotas | `test_f21_reliability_dashboard_*` | Empty events, uninitialized circuit | Quota gauges + circuit status | Real-time reliability monitoring |
| **F-22** | Settings, Audit Log & Developer Docs | `test_f22_settings_and_docs_*` | RPM limit bounds, account deletion | Audit log event pagination | Documentation snippet verification |
| **F-23** | E2E Testing Suite (Tiers 1–4) | `test_f23_test_suite_harness_*` | Harness timeout, mock transport errors | Multi-tier runner execution | Complete regression pass |
| **F-24** | Final Integration & Adversarial Verification | `test_f24_integration_verification_*` | Boundary and stress injection | Adversarial payload validation | Full platform acceptance |

---

## 4. Test Harness Architecture & Directories

```
backend/tests/e2e/
├── conftest.py                # Isolated fixtures: mock transports, test DB, virtual keys, dev users
├── test_tier1_features.py     # Tier 1: 120+ tests covering Features 1-24 in isolation
├── test_tier2_boundaries.py   # Tier 2: Boundary, limit, rate-limit (429), and fault injection tests
├── test_tier3_combinations.py # Tier 3: Pairwise cross-feature interactions (streaming, failover, quotas)
└── test_tier4_workloads.py    # Tier 4: Real-world multi-turn chat, high concurrency, and admin flows
```

### Shared Fixtures (`backend/tests/e2e/conftest.py`)
- `e2e_db`: Fresh async database session bound to transaction rollback or clean user scope.
- `e2e_client`: `httpx.AsyncClient` targeting the FastAPI application via `ASGITransport`.
- `mock_provider_pool`: Controllable mock transport simulating Google Gemini, Groq, and OpenRouter endpoints with programmable fault injection (HTTP status, latency, response headers, stream chunks).
- `e2e_user_and_key`: Helper creating a test user, registered provider credentials, synchronized models, and an active virtual API key.

---

## 5. Execution Commands

### Run Entire E2E Suite:
```powershell
uv run pytest backend/tests/e2e/ -v
```

### Run by Specific Tier:
```powershell
uv run pytest backend/tests/e2e/test_tier1_features.py -v
uv run pytest backend/tests/e2e/test_tier2_boundaries.py -v
uv run pytest backend/tests/e2e/test_tier3_combinations.py -v
uv run pytest backend/tests/e2e/test_tier4_workloads.py -v
```

### Run Quick Smoke Check:
```powershell
uv run pytest backend/tests/e2e/test_tier1_features.py -k "test_f01 or test_f03" -v
```
