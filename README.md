# Unified AI Gateway

A high-performance, asynchronous AI API Gateway built with FastAPI, SQLAlchemy 2.x, PostgreSQL, and Redis. The gateway provides unified multi-provider routing, centralized credential vault encryption, model discovery normalization, and infrastructure health monitoring.

---

## 1. Project Overview & Progress

The gateway is built iteratively:

- **Phase 1: Core Infrastructure (Complete)**
  - Async database engine with connection pooling and lifecycle hooks.
  - Reusable Redis connection manager.
  - Configuration management backed by Pydantic Settings v2.
  - Liveness (`/health/live`) and readiness (`/health/ready`) probes.
  - Containerization and base Alembic migration infrastructure.

- **Phase 2: Provider Integration Layer & Credential Vault (Complete)**
  - **Provider Abstraction Architecture:** Abstract `BaseProvider` interface and central `ProviderManager` registry.
  - **Supported Integrations:** Google Gemini, Groq, and OpenRouter.
  - **Model Discovery Normalization:** Unified `UnifiedModel` schema normalizing context windows, modalities, capabilities, and pricing.
  - **Capability Confidence Classification:** Unambiguous certainty tracking (`confirmed`, `inferred`, `unknown`) to empower safe, reliable dynamic routing decisions.
  - **Credential Vault & Key Versioning:** Hardware-grade AES-256-GCM authenticated encryption at rest with 12-byte random nonces, key versioning (`v1:...`, `v2:...`), online key rotation without access loss, and keyed HMAC-SHA256 duplicate detection.
  - **Authentication Boundary:** Development-only identity dependency (`get_current_user`), failing closed and rejecting dev identity in production.
  - **Database Migrations:** Alembic migrations for `users` and `provider_credentials` with referential integrity, composite uniqueness constraints, and key version tracking.
  - **Provider API Endpoints:** Endpoints to list providers, securely connect credentials, list masked credentials, validate credentials against upstream APIs, rotate encryption keys, and discover models.

- **Phase 3: Unified Model Registry (Complete)**
  - **Persistent Normalized Model Registry:** Separation of canonical model identity (`UnifiedModel`) from provider-specific offerings (`ProviderModel`) and audit logs (`ModelSyncLog`).
  - **Model Normalization & Identity Resolution:** Vendor namespace resolution rules (`google/...`, `meta-llama/...`, `openai/...`), routing tier suffix stripping, and modality classification without false cross-model merging.
  - **Capability Provenance System:** Structured 3-state tracking (`confirmed`, `inferred`, `unknown`) across vision, tool calling, streaming, reasoning, and structured output.
  - **Asynchronous Registry Synchronization:** Idempotent discovery service querying connected credentials, upserting catalog entries, reconciling missing models as unavailable without losing historical records, and resilient audit logging.
  - **User Isolation & Data Boundaries:** Queries and model listings strictly scoped to the authenticated user's credentials; zero leakage of another user's connected provider offerings.
  - **Model Discovery API Endpoints:** Multi-dimensional filtering (`/api/v1/models`), provider availability summaries (`/api/v1/models/providers`), manual sync triggers (`/api/v1/models/sync`), sync audit history (`/api/v1/models/sync/status`), and model details (`/api/v1/models/{model_id}`).
  - **Alembic Migration:** Applied revision `6403bf8a3402` to Supabase PostgreSQL with cascade foreign keys, JSONB metadata, and composite unique indexes.

- **Phase 4: Unified API Gateway (Complete)**
  - **OpenAI-Compatible Chat Completions:** `POST /v1/chat/completions` supporting non-streaming and Server-Sent Events (SSE) streaming responses with token accounting.
  - **Virtual API Key Management:** Platform-generated virtual API keys (`uag_live_...`) with HMAC-SHA256 hashed storage, key prefix indexing, constant-time validation, rotation, and revocation (`/api/v1/keys`).
  - **OpenAI Models Catalog:** `GET /v1/models` returning models available under the virtual key owner's validated credentials in OpenAI format.
  - **Explicit Model Resolution:** `{provider}:{provider_model_id}` namespacing (e.g. `gemini:gemini-2.5-flash`, `groq:llama-3.3-70b-versatile`, `openrouter:openai/gpt-4o`) with ownership verification and in-memory credential decryption.
  - **Provider-Specific Request Translation:** Translates OpenAI schemas (system instructions, user/assistant roles, temperature, top_p, max_tokens) to upstream provider formats.
  - **Provider Response Normalization:** Standardizes upstream responses into canonical OpenAI `ChatCompletionResponse` and `ChatCompletionChunk` SSE streams.
  - **Rate Limiting & Abuse Prevention:** Atomic database-backed fixed window counter (default 60 RPM) returning HTTP 429 with `Retry-After`.
  - **Usage Tracking & Audit Logging:** Asynchronous logging of latency, token counts, status, and error summaries (`gateway_request_logs`). Zero raw API key, credential secret, or prompt logging.
  - **Standardized Error Envelope:** Strict OpenAI-compatible JSON error format for 400, 401, 404, 429, 500, and 502 status codes.
  - **Alembic Migration:** Applied revision `5c0a5ca5af5f` to Supabase PostgreSQL for `virtual_api_keys`, `gateway_request_logs`, and `rate_limit_buckets`.

---

## 2. Provider Abstraction Architecture

```mermaid
flowchart TD
    Client["Client / Frontend"] -->|"POST /providers/{provider}/credentials"| Routes["FastAPI Provider Routes"]
    Client -->|"GET /providers/credentials/{id}/models"| Routes

    subgraph Auth ["Authentication Boundary"]
        Routes --> AuthDep["get_current_user Dependency"]
        AuthDep -->|"Dev Mode (ENABLE_DEV_AUTH)"| DevUser["Development User Identity"]
        AuthDep -.->|"Production Mode"| OAuth["Future Google OAuth (Phase 3)"]
    end

    subgraph Vault ["Credential Vault Service"]
        Routes --> CredService["CredentialService"]
        CredService --> Enc["AES-256-GCM Encryption"]
        CredService --> HMAC["HMAC-SHA256 Fingerprinting"]
        CredService --> DB[("PostgreSQL (users & provider_credentials)")]
    end

    subgraph ProviderLayer ["Provider Integration Layer"]
        Routes --> Manager["ProviderManager"]
        Manager --> AdapterRegistry{"Adapter Registry"}
        AdapterRegistry --> Gemini["GeminiProvider"]
        AdapterRegistry --> Groq["GroqProvider"]
        AdapterRegistry --> OpenRouter["OpenRouterProvider"]
        AdapterRegistry -.-> Custom["Future Providers"]
    end

    subgraph UpstreamAPIs ["Upstream AI Services"]
        Gemini -->|"GET /v1beta/models"| GoogleAI["Google Gemini API"]
        Groq -->|"GET /openai/v1/models"| GroqAPI["Groq LPU Engine"]
        OpenRouter -->|"GET /api/v1/auth/key & /models"| OpenRouterAPI["OpenRouter Gateway"]
    end
```

### Key Architectural Principles

1. **Strict Interface Contract:** Every provider implements `BaseProvider` exposing `validate_credentials(api_key)` and `list_models(api_key)`.
2. **Normalized Models:** Raw provider responses are mapped into the standard `UnifiedModel` Pydantic model. Provider-specific raw fields are segregated into `metadata`.
3. **No Provider Logic in Routes:** Route handlers interact solely with `CredentialService` and `ProviderManager`.
4. **Normalized Error Handling:** Status codes across all providers are normalized into `InvalidCredentialsError` (401/403), `RateLimitError` (429), `ProviderUnavailableError` (5xx), and `ProviderTimeoutError`. Secrets are never exposed in exception messages.

---

## 3. Supported Integrations & Obtaining API Keys

| Provider | Provider ID | Capabilities | Key Documentation |
|---|---|---|---|
| **Google Gemini** | `gemini` | Multimodal (Text, Image, Audio, Video), up to 2M tokens context, function calling | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| **Groq** | `groq` | Ultra-fast LPU inference (Llama 3.3, Gemma, Whisper, Mixtral) | [Groq Console](https://console.groq.com/keys) |
| **OpenRouter** | `openrouter` | Aggregated catalog of 200+ models with dynamic pricing and free-tier models | [OpenRouter Keys](https://openrouter.ai/keys) |

---

## 4. Credential Vault & Cryptographic Design

The Credential Vault secures API keys at rest using **AES-256-GCM** via the Python `cryptography` library.

### Security Guarantees:
- **Dedicated Key:** A 32-byte encryption key (`CREDENTIAL_ENCRYPTION_KEY`) loaded from the environment (fail-closed if missing).
- **Fresh Nonce:** Every encryption generates a fresh random 96-bit (12-byte) nonce via `os.urandom(12)`. Identical plaintexts produce completely different ciphertexts.
- **Authenticated Integrity:** AES-256-GCM generates a 128-bit authentication tag. Any tampering with the ciphertext or nonce causes decryption to fail immediately.
- **Deterministic Keyed Fingerprint:** Duplicate detection uses `HMAC-SHA256(key, api_key)` to detect duplicate credentials per user without decrypting or storing plaintext lookup keys.
- **Masked Keys:** API responses and logs display masked representations (e.g. `gsk_...9988`). Plaintext API keys are never stored, logged, or returned.

---

## 5. Environment Configuration

Add the following configuration to your `.env` file:

```env
# Core Application Configuration
APP_NAME="Unified AI Gateway"
APP_ENV="development"
DEBUG=true
API_V1_PREFIX="/api/v1"

# Database Configuration (Supabase PostgreSQL)
DATABASE_URL="postgresql+asyncpg://gateway_user:password@aws-0-region.pooler.supabase.com:6543/postgres"

# Redis Cache Configuration
REDIS_URL="redis://localhost:6379/0"

# Credential Vault Configuration (Phase 2)
# Generate a 32-byte key: python -c "import secrets; print(secrets.token_hex(32))"
CREDENTIAL_ENCRYPTION_KEY="your-32-byte-hex-key"

# Outbound HTTP request timeout for provider calls (seconds)
PROVIDER_REQUEST_TIMEOUT=30.0

# Development-only authentication boundary (MUST be false in production)
ENABLE_DEV_AUTH=true
```

---

## 6. Provider API Endpoints

### 1. List Supported Providers
- **Method:** `GET`
- **Path:** `/api/v1/providers`
- **Example Response:**
  ```json
  {
    "providers": [
      {
        "id": "gemini",
        "name": "Google Gemini",
        "description": "Google DeepMind foundation models supporting multimodal intelligence...",
        "website_url": "https://ai.google.dev",
        "docs_url": "https://ai.google.dev/api/models"
      },
      {
        "id": "groq",
        "name": "Groq",
        "description": "Ultra-fast LPU inference engine for open-weights models...",
        "website_url": "https://groq.com",
        "docs_url": "https://console.groq.com/docs/api-reference"
      },
      {
        "id": "openrouter",
        "name": "OpenRouter",
        "description": "Unified gateway to frontier, open-source, and specialized models...",
        "website_url": "https://openrouter.ai",
        "docs_url": "https://openrouter.ai/docs"
      }
    ]
  }
  ```

### 2. Connect & Encrypt Provider Credential
- **Method:** `POST`
- **Path:** `/api/v1/providers/{provider}/credentials`
- **Headers:** `X-Dev-User-Email: user@example.com`
- **Request Body:**
  ```json
  {
    "api_key": "gsk_your_groq_api_key_here",
    "display_name": "Groq Production Key"
  }
  ```
- **Response (HTTP 201 Created):**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "provider": "groq",
    "display_name": "Groq Production Key",
    "status": "active",
    "masked_key": "gsk_...9988",
    "last_validated_at": "2026-11-07T10:45:00Z",
    "created_at": "2026-11-07T10:45:00Z",
    "updated_at": "2026-11-07T10:45:00Z"
  }
  ```

### 3. List User Credentials
- **Method:** `GET`
- **Path:** `/api/v1/providers/credentials`
- **Headers:** `X-Dev-User-Email: user@example.com`
- **Response (HTTP 200 OK):**
  ```json
  [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "provider": "groq",
      "display_name": "Groq Production Key",
      "status": "active",
      "masked_key": "gsk_...9988",
      "last_validated_at": "2026-11-07T10:45:00Z",
      "created_at": "2026-11-07T10:45:00Z",
      "updated_at": "2026-11-07T10:45:00Z"
    }
  ]
  ```

### 4. Validate Stored Credential
- **Method:** `POST`
- **Path:** `/api/v1/providers/credentials/{credential_id}/validate`
- **Response (HTTP 200 OK):**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "provider": "groq",
    "status": "active",
    "is_valid": true,
    "last_validated_at": "2026-11-07T10:50:00Z",
    "message": "Credential validated successfully"
  }
  ```

### 5. Discover Models for Credential
- **Method:** `GET`
- **Path:** `/api/v1/providers/credentials/{credential_id}/models`
- **Response (HTTP 200 OK):**
  ```json
  [
    {
      "id": "llama-3.3-70b-versatile",
      "provider": "groq",
      "name": "llama-3.3-70b-versatile",
      "context_window": 131072,
      "input_modalities": ["text"],
      "output_modalities": ["text"],
      "supports_streaming": true,
      "supports_tools": true,
      "pricing": null,
      "metadata": {
        "owned_by": "Meta",
        "active": true
      }
    }
  ]
  ```

### 6. Rotate Credential Encryption Key
- **Method:** `POST`
- **Path:** `/api/v1/providers/credentials/{credential_id}/rotate`
- **Request Body (Optional):**
  ```json
  {
    "target_version": 2
  }
  ```
- **Response (HTTP 200 OK):**
  ```json
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "provider": "groq",
    "key_version": 2,
    "updated_at": "2026-11-07T11:20:00Z",
    "message": "Credential encryption key rotated successfully"
  }
  ```

### 7. Revoke & Delete Credential
- **Method:** `DELETE`
- **Path:** `/api/v1/providers/credentials/{credential_id}`
- **Response:** HTTP 204 No Content.

---

## 7. Unified Model Registry Architecture (Phase 3)

The Unified Model Registry provides persistent, normalized storage and discovery of AI models available across connected provider credentials, separating the abstract identity of an AI model from its physical provider offering.

```mermaid
flowchart TD
    Client["Client / SDK / Future Router"] -->|"GET /api/v1/models"| ModelsAPI["Models Route (/models)"]
    Client -->|"POST /api/v1/models/sync"| ModelsAPI
    Client -->|"GET /api/v1/models/{model_id}"| ModelsAPI

    subgraph ServiceLayer ["Model Registry & Sync Services"]
        ModelsAPI --> RegistryService["ModelRegistryService"]
        ModelsAPI --> SyncService["ModelSyncService"]
        SyncService --> Normalizer["ModelNormalizer"]
        SyncService --> CredService["CredentialService (Vault)"]
        SyncService --> Manager["ProviderManager"]
    end

    subgraph DatabaseSchema ["Supabase PostgreSQL (Alembic: 6403bf8a3402)"]
        RegistryService -->|"User-Scoped Query"| PM[("provider_models Offering Table")]
        RegistryService -->|"Canonical Info"| UM[("unified_models Canonical Table")]
        SyncService -->|"Idempotent Upsert"| UM
        SyncService -->|"Reconcile Availability"| PM
        SyncService -->|"Audit Operation"| MSL[("model_sync_logs History Table")]
        PM -->|"FK (Cascade)"| UM
        PM -->|"FK (Cascade)"| PC[("provider_credentials")]
        MSL -->|"FK (Cascade)"| Users[("users")]
    end

    subgraph Providers ["Upstream Providers"]
        Manager --> GeminiAdapter["Gemini API"]
        Manager --> GroqAdapter["Groq API"]
        Manager --> OpenRouterAdapter["OpenRouter API"]
    end
```

### Core Architecture Concepts

#### A. Canonical Model (`UnifiedModel`)
Represents the provider-agnostic identity of a model (e.g. `google/gemini-2.5-flash`, `openai/gpt-4o`, `meta-llama/llama-3.3-70b-versatile`).
- Models from different providers are **only merged when identity can be confirmed with high confidence** (e.g. matching vendor namespace and clean base model ID).
- Different versions (e.g., `gemini-1.5-flash` vs. `gemini-2.5-flash`) are **never merged**.
- Display names are never used as a merging heuristic.

#### B. Provider Offering (`ProviderModel`)
Represents a specific offering of a canonical model bound to a user's connected provider credential.
- Tracks exact provider model ID (`provider_model_id`), context windows, maximum output tokens, normalized pricing per 1M tokens, functional capability flags, and availability status (`available`, `unavailable`, `unknown`).
- **Composite Uniqueness:** `UniqueConstraint("credential_id", "provider", "provider_model_id")` ensures that one user's credential-specific offering never collides with or leaks into another user's offerings.

#### C. Synchronization Audit Log (`ModelSyncLog`)
Tracks every discovery synchronization run per user and credential:
- Tracks status (`in_progress`, `completed`, `failed`, `partial_failure`), timestamps, counts of models discovered, added, updated, and marked unavailable.
- **Strict Secret Hygiene:** Never logs decrypted API keys, raw authorization headers, or sensitive credentials.

---

## 8. Model Normalization & Capability Provenance

### Normalization Rules

| Provider | Raw Model ID Example | Normalized Canonical ID | Rules & Rationale |
|---|---|---|---|
| **Gemini** | `models/gemini-2.5-flash` | `google/gemini-2.5-flash` | Strips `models/` prefix and scopes to canonical `google/` vendor namespace. |
| **OpenRouter** | `google/gemini-2.5-flash` | `google/gemini-2.5-flash` | Already vendor-scoped; merges with Google's direct canonical model while offering is isolated. |
| **OpenRouter** | `liquid/lfm-3-1.7b:free` | `liquid/lfm-3-1.7b` | Strips provider routing tier variants (`:free`, `:extended`, `:nitro`) for canonical identity while retaining raw ID in offering. |
| **Groq** | `openai/gpt-oss-20b` | `openai/gpt-oss-20b` | Preserves explicit vendor namespace. |
| **Groq** | `llama-3.3-70b-versatile` | `meta-llama/llama-3.3-70b-versatile` | Resolves known model family (`llama`) to canonical publisher namespace (`meta-llama`). |
| **Groq** | `allam-2-7b` | `groq/allam-2-7b` | Unrecognized vendor family falls back to provider namespace to prevent false merging. |

### Capability Provenance (3-State Certainty)

To prevent the future intelligent router from selecting models based on unverified assumptions, every capability is classified with explicit provenance:
1. **Confirmed (`confirmed`):** Declared explicitly in upstream provider API responses (e.g., `inputTokenLimit`, `architecture.modality`).
2. **Inferred (`inferred`):** Deduced via model family naming conventions (e.g. `vision` in model name).
3. **Unknown (`unknown`):** No upstream data or reliable heuristic available.

Stored in `ProviderModel.capability_metadata` as structured JSON:
```json
{
  "streaming": {"supported": true, "confidence": "confirmed", "source": "provider_api"},
  "tools": {"supported": true, "confidence": "confirmed", "source": "provider_api"},
  "vision": {"supported": true, "confidence": "confirmed", "source": "provider_api"},
  "structured_output": {"supported": null, "confidence": "unknown", "source": "unknown"},
  "reasoning": {"supported": null, "confidence": "unknown", "source": "unknown"}
}
```

### Pricing Normalization
Pricing is normalized to **USD per 1,000,000 tokens** (`input_price_per_million` and `output_price_per_million`):
- OpenRouter token prices (e.g. `$0.000000075 / token`) are scaled to `$0.075 / 1M tokens`.
- Providers that do not expose pricing (Gemini, Groq) remain `NULL`. Gateway never invents pricing.

---

## 9. Model Registry API Endpoints

All endpoints are authenticated and strictly scoped to the authenticated user.

### 1. List Available Models (with Multi-Dimensional Filtering)
- **Method:** `GET`
- **Path:** `/api/v1/models`
- **Query Parameters:**
  - `provider`: Filter by provider (`gemini`, `groq`, `openrouter`).
  - `modality`: Filter by canonical modality (`text->text`, `multimodal`, `audio`, `embedding`).
  - `input_modality`: Filter by input modality (`text`, `image`, `audio`).
  - `output_modality`: Filter by output modality (`text`, `image`).
  - `capability`: Filter by verified capability (`vision`, `tools`, `streaming`, `structured_output`, `reasoning`).
  - `availability_status`: Status filter (`available` [default], `unavailable`, `all`).
  - `limit`: Pagination limit (default 50, max 100).
  - `offset`: Pagination offset (default 0).
- **Response (HTTP 200 OK):**
  ```json
  {
    "total": 1,
    "limit": 50,
    "offset": 0,
    "items": [
      {
        "id": "464279dd-d7a6-48f6-8b73-a78e251c92c9",
        "canonical_id": "google/gemini-2.5-flash",
        "display_name": "Google: Gemini 2.5 Flash",
        "description": "Next-generation multimodal model with 1M context window",
        "provider_model_family": "gemini",
        "modality": "multimodal",
        "input_modalities": ["text", "image", "audio", "video"],
        "output_modalities": ["text"],
        "created_at": "2026-11-07T12:00:00Z",
        "updated_at": "2026-11-07T12:00:00Z",
        "provider_offerings": [
          {
            "id": "7693005f-139c-4933-ae5b-bcd87843acab",
            "provider": "gemini",
            "provider_model_id": "gemini-2.5-flash",
            "credential_id": "815fc91f-d539-404b-ac89-1c8d990ad2c0",
            "context_window": 1048576,
            "max_output_tokens": 65536,
            "input_price_per_million": null,
            "output_price_per_million": null,
            "supports_streaming": true,
            "supports_tools": true,
            "supports_vision": true,
            "availability_status": "available",
            "metadata_source": "provider_api",
            "capability_metadata": { ... },
            "last_seen_at": "2026-11-07T12:00:00Z",
            "last_verified_at": "2026-11-07T12:00:00Z"
          }
        ]
      }
    ]
  }
  ```

### 2. Get Provider Availability Summary
- **Method:** `GET`
- **Path:** `/api/v1/models/providers`
- **Response (HTTP 200 OK):**
  ```json
  {
    "providers": [
      {
        "provider": "gemini",
        "total_models": 61,
        "available_models": 61,
        "credentials_count": 1,
        "modalities": ["audio", "embedding", "text->text"]
      },
      {
        "provider": "groq",
        "total_models": 11,
        "available_models": 11,
        "credentials_count": 1,
        "modalities": ["audio", "text->text"]
      },
      {
        "provider": "openrouter",
        "total_models": 424,
        "available_models": 424,
        "credentials_count": 1,
        "modalities": ["audio", "multimodal", "text->text"]
      }
    ]
  }
  ```

### 3. Trigger Model Discovery Synchronization
- **Method:** `POST`
- **Path:** `/api/v1/models/sync`
- **Request Body (Optional):**
  ```json
  {
    "provider": "gemini",
    "credential_id": null
  }
  ```
- **Response (HTTP 200 OK):**
  ```json
  {
    "sync_id": "d4e7665b-c4a2-42b1-b689-470fd5e70c18",
    "status": "completed",
    "started_at": "2026-11-07T12:03:00Z",
    "completed_at": "2026-11-07T12:03:02Z",
    "total_discovered": 61,
    "total_added": 61,
    "total_updated": 0,
    "total_marked_unavailable": 0,
    "credentials_synced": [
      {
        "credential_id": "72a45818-a02c-4853-8ffc-1a18c588df49",
        "provider": "gemini",
        "status": "completed",
        "models_discovered": 61,
        "models_added": 61,
        "models_updated": 0,
        "models_marked_unavailable": 0,
        "error_summary": null
      }
    ],
    "errors": []
  }
  ```

### 4. Get Synchronization Status and Audit History
- **Method:** `GET`
- **Path:** `/api/v1/models/sync/status?limit=20`
- **Response (HTTP 200 OK):**
  ```json
  {
    "logs": [
      {
        "id": "c2e4cf01-ed28-47f6-85aa-3f7755df5e46",
        "user_id": "3cb14c98-e0f6-432b-8848-9467212b794f",
        "provider": "gemini",
        "credential_id": "72a45818-a02c-4853-8ffc-1a18c588df49",
        "status": "completed",
        "started_at": "2026-11-07T12:07:24Z",
        "completed_at": "2026-11-07T12:07:25Z",
        "models_discovered": 61,
        "models_added": 0,
        "models_updated": 61,
        "models_marked_unavailable": 0,
        "error_summary": null
      }
    ]
  }
  ```

### 5. Get Detailed Canonical Model Information
- **Method:** `GET`
- **Path:** `/api/v1/models/{model_id}` (Supports UUID or canonical ID e.g. `/api/v1/models/google/gemini-2.5-flash`)
- **Response (HTTP 200 OK):** Returns `UnifiedModelRead` with canonical data and user-owned offerings. Returns 404 if the user has no connected credentials offering the model.

---

## 10. Unified API Gateway (/v1) & Virtual Key Architecture

Phase 4 transforms the gateway into an OpenAI-compatible proxy interface. External applications, developer tools, and the official OpenAI SDK can consume any configured upstream provider (Google Gemini, Groq, OpenRouter) seamlessly using platform-issued **Virtual API Keys**.

```mermaid
flowchart TD
    Client["Client Application / OpenAI SDK"] -->|"POST /v1/chat/completions\nAuthorization: Bearer uag_live_..."| Gateway["Gateway Router (/v1)"]

    subgraph AuthRL ["1. Authentication & Rate Limiting"]
        Gateway --> Auth["Gateway Auth Dependency"]
        Auth -->|"HMAC-SHA256 Hash Lookup"| VKeyDB[("virtual_api_keys")]
        Auth --> RL["Rate Limiter (PostgreSQL)"]
        RL -->|"Atomic Counter (Default 60 RPM)"| RLDB[("rate_limit_buckets")]
    end

    subgraph Resolution ["2. Model & Credential Resolution"]
        RL --> Resolver["ModelResolverService"]
        Resolver -->|"Parse {provider}:{model_id}"| PModelDB[("provider_models")]
        Resolver -->|"Verify Ownership & Status"| CredDB[("provider_credentials")]
        Resolver -->|"AES-256-GCM In-Memory Decrypt"| PlainKey["Decrypted Upstream API Key"]
    end

    subgraph Execution ["3. Translation & Upstream Execution"]
        PlainKey --> Adapter["Provider Adapter\n(Gemini / Groq / OpenRouter)"]
        Adapter -->|"Translate Payload"| UpstreamAPI["Upstream AI Provider"]
        UpstreamAPI -->|"Raw Response / Chunks"| Adapter
        Adapter -->|"Normalize to OpenAI Envelope"| Normalizer["Response Normalizer"]
    end

    subgraph OutputLogging ["4. Delivery & Usage Tracking"]
        Normalizer -->|"JSON / SSE Stream"| Client
        Normalizer -.->|"Asynchronous Audit Log"| LogSvc["GatewayUsageService"]
        LogSvc -->|"Record Latency, Tokens, Status"| LogDB[("gateway_request_logs")]
    end
```

---

### Virtual API Key Management

Virtual API keys decouple external clients from upstream provider secrets:
- **Format:** `uag_live_` followed by 32 cryptographically secure random bytes (Base64URL encoded).
- **Security:** Secret keys are shown **only once** upon creation. Only the 16-character prefix (`key_prefix`) and HMAC-SHA256 hash (`key_hash`) are persisted.
- **Constant-Time Verification:** Uses `hmac.compare_digest` to prevent timing attacks.

#### Key Management Endpoints (`/api/v1/keys`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/keys` | Create a new virtual API key (returns raw key once). |
| `GET` | `/api/v1/keys` | List all virtual keys for the user (masked secrets). |
| `GET` | `/api/v1/keys/{key_id}` | Retrieve metadata and last-used timestamp for a key. |
| `POST` | `/api/v1/keys/{key_id}/rotate` | Invalidate current secret and issue a fresh secret under the same ID. |
| `DELETE` | `/api/v1/keys/{key_id}` | Revoke key immediately (`is_active = False`). |

---

### Gateway Model Addressing

To avoid ambiguity across multiple providers offering identical open-weights models (e.g. Llama 3 on Groq vs. OpenRouter), model requests use the explicit namespaced identifier format:

```text
{provider}:{provider_model_id}
```

#### Examples:
- **Google Gemini:** `gemini:gemini-2.5-flash`, `gemini:gemini-2.5-pro`
- **Groq:** `groq:llama-3.3-70b-versatile`, `groq:mixtral-8x7b-32768`
- **OpenRouter:** `openrouter:openai/gpt-4o`, `openrouter:anthropic/claude-3.5-sonnet`

---

### OpenAI-Compatible Chat Completions (`POST /v1/chat/completions`)

#### Supported Parameters:
- `model` *(string, required)*: The namespaced model identifier (`{provider}:{provider_model_id}`).
- `messages` *(array, required)*: List of chat messages with `role` (`system`, `user`, `assistant`) and `content`.
- `temperature` *(float, optional)*: Sampling temperature between 0.0 and 2.0.
- `top_p` *(float, optional)*: Nucleus sampling probability.
- `max_tokens` / `max_completion_tokens` *(integer, optional)*: Maximum generation budget.
- `stream` *(boolean, optional)*: If `true`, emits Server-Sent Events (SSE) data chunks.

#### Streaming Protocol:
Streams standard Server-Sent Events formatted as:
```text
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"groq:llama-3.3-70b-versatile","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"groq:llama-3.3-70b-versatile","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":"stop"}]}

data: [DONE]
```

---

### Standardized Error Format

All errors originating from the `/v1` gateway conform to the OpenAI error envelope:

```json
{
  "error": {
    "message": "Model 'groq:unknown-model' was not found or is not available for this account",
    "type": "invalid_request_error",
    "param": "model",
    "code": "model_not_found"
  }
}
```

| HTTP Status | Error Type | Error Codes |
|---|---|---|
| `400 Bad Request` | `invalid_request_error` | `invalid_model_format`, `model_unavailable`, `invalid_payload` |
| `401 Unauthorized` | `authentication_error` | `missing_api_key`, `invalid_api_key`, `key_revoked`, `key_expired` |
| `404 Not Found` | `invalid_request_error` | `model_not_found` |
| `429 Too Many Requests` | `rate_limit_error` | `rate_limit_exceeded` *(includes `Retry-After` header)* |
| `500 Internal Error` | `api_error` | `internal_error` |
| `502 Bad Gateway` | `upstream_error` | `provider_error`, `provider_timeout`, `upstream_rate_limited` |

---

### Rate Limiting & Usage Tracking

1. **Fixed-Window Rate Limiting:** Enforces requests-per-minute (`GATEWAY_RATE_LIMIT_RPM`, default 60) per virtual key via PostgreSQL row-level atomic transactions in `rate_limit_buckets`.
2. **Audit Logging & Analytics:** Each completed request records latency, token breakdown (input, completion, total), and error status in `gateway_request_logs`. **Prompt text, completions, and raw API keys are never stored in request logs.**
3. **Usage Endpoints:**
   - `GET /api/v1/usage/summary`: Aggregate metrics (total requests, total tokens, average latency, success/error counts).
   - `GET /api/v1/usage/requests`: Paginated request audit history.

---

### Examples & Client Integration

#### 1. Generate a Virtual API Key
```bash
curl -X POST http://localhost:8000/api/v1/keys \
  -H "Content-Type: application/json" \
  -H "X-Dev-User-Email: user@example.com" \
  -d '{"name": "Production Web App"}'
```
Response:
```json
{
  "id": "67a3f81e-bbd2-43ce-9ea7-64dfd60e7f22",
  "name": "Production Web App",
  "key_prefix": "uag_live_7A9f2K",
  "key": "uag_live_7A9f2K...raw_secret_only_shown_once...",
  "is_active": true,
  "created_at": "2026-11-07T12:00:00Z"
}
```

#### 2. Query Available Models via OpenAI Catalog
```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer uag_live_YOUR_VIRTUAL_KEY"
```

#### 3. Non-Streaming Chat Completion
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer uag_live_YOUR_VIRTUAL_KEY" \
  -d '{
    "model": "groq:llama-3.3-70b-versatile",
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "Explain quantum entanglement in 1 sentence."}
    ],
    "temperature": 0.5
  }'
```

#### 4. Streaming Chat Completion via SSE
```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer uag_live_YOUR_VIRTUAL_KEY" \
  -d '{
    "model": "gemini:gemini-2.5-flash",
    "messages": [
      {"role": "user", "content": "Count from 1 to 5 slowly."}
    ],
    "stream": true
  }'
```

#### 5. Official OpenAI Python SDK Integration
```python
from openai import OpenAI

# Point client to the Unified AI Gateway
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="uag_live_YOUR_VIRTUAL_KEY",
)

# 1. Non-streaming call (Groq)
response = client.chat.completions.create(
    model="groq:llama-3.3-70b-versatile",
    messages=[
        {"role": "system", "content": "You are an expert engineer."},
        {"role": "user", "content": "What is the primary benefit of HTTP/2?"},
    ],
    temperature=0.7,
)
print("Groq Response:", response.choices[0].message.content)

# 2. Streaming call (Gemini)
stream = client.chat.completions.create(
    model="gemini:gemini-2.5-flash",
    messages=[{"role": "user", "content": "Write a short haiku about code."}],
    stream=True,
)
print("Gemini Stream: ", end="")
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()
```

---

## 11. How to Add a New Provider Adapter

Adding a new provider does not require modifying existing adapters:

1. Create a new adapter file in `backend/app/providers/adapters/<provider_name>.py`:
   ```python
   from app.providers.base import BaseProvider
   from app.providers.schemas.model import UnifiedModel
   from app.providers.schemas.provider import ProviderInfo


   class AnthropicProvider(BaseProvider):
       @property
       def provider_id(self) -> str:
           return "anthropic"

       @property
       def provider_info(self) -> ProviderInfo:
           return ProviderInfo(
               id="anthropic",
               name="Anthropic",
               docs_url="https://docs.anthropic.com",
           )

       async def validate_credentials(self, api_key: str) -> bool: ...

       async def list_models(self, api_key: str) -> list[UnifiedModel]: ...
   ```
2. Register the adapter in `backend/app/providers/manager.py`:
   ```python
   self.register_provider(AnthropicProvider())
   ```
3. Export from `backend/app/providers/adapters/__init__.py`.

---

## 12. Known Limitations & Registry Notes

- **Google Gemini:** Dynamic token pricing is not exposed via the v1beta models endpoint (`pricing: null`). Token limits are accurately populated from `inputTokenLimit` and `outputTokenLimit`.
- **Groq:** Groq exposes `context_window` directly on each model object. Tool calling support is inferred from model family tags (e.g. Llama 3). Dynamic token pricing is not exposed via the REST API (`pricing: null`).
- **OpenRouter:** Models catalog includes detailed prompt and completion pricing, which is normalized to USD per 1M tokens. Free models are categorized automatically based on zero pricing or `:free` suffix.
- **Model Identity Boundaries:** Cross-provider model merging is performed conservatively. Models with distinct versions or ambiguous publisher identity are never falsely merged.
- **User Scoping:** All model queries require an authenticated user and only return provider offerings matching the active user's credentials.

---

## 13. Running Tests & Verification

### Complete Automated Pytest Suite
Run the 74 automated tests with full mocks:
```bash
cd backend
uv run pytest -v
```

### Manual Integration Testing with Real API Credentials (Optional)
If you have a live provider API key, you can test it directly via the development API:

1. Start the gateway:
   ```bash
   uvicorn app.main:app --reload
   ```
2. Register credential:
   ```bash
   curl -X POST http://localhost:8000/api/v1/providers/groq/credentials \
     -H "Content-Type: application/json" \
     -H "X-Dev-User-Email: test@example.com" \
     -d '{"api_key": "gsk_your_real_key", "display_name": "My Groq Key"}'
   ```
3. Trigger Model Discovery & Sync:
   ```bash
   curl -X POST http://localhost:8000/api/v1/models/sync \
     -H "X-Dev-User-Email: test@example.com"
   ```
4. Query Normalized Registry with Filters:
   ```bash
   curl "http://localhost:8000/api/v1/models?capability=vision" \
     -H "X-Dev-User-Email: test@example.com"
   ```

### Code Formatting & Linting
```bash
cd backend
uv run ruff check .
uv run ruff format --check .
```
