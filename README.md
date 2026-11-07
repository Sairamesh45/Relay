# Unified AI Gateway — Phase 1: Core Infrastructure

A high-performance, asynchronous API Gateway foundation built with FastAPI, SQLAlchemy 2.x, PostgreSQL, and Redis. This core infrastructure establishes connection pooling, configuration management, health probing, and containerization for a multi-provider AI routing and orchestration platform.

---

## 1. Project Overview

The **Unified AI Gateway** is designed to provide centralized governance, intelligent load balancing, and failover across multiple Large Language Model (LLM) providers. 

**Phase 1** establishes the mission-critical foundation:
- Asynchronous database engine with connection pooling and lazy connection initialization.
- Reusable Redis connection manager with health probing and lifecycle hooks.
- Strict configuration management backed by Pydantic Settings and environment validation.
- Standardized liveness (`/health/live`) and readiness (`/health/ready`) probes.
- Alembic database migration environment prepared for declarative model expansion.
- Production-grade containerization with Docker Compose and a non-root Dockerfile.

---

## 2. Architecture

```mermaid
flowchart TD
    Client["Client / Load Balancer"] -->|"HTTP Requests"| Gateway["FastAPI Application"]
    
    subgraph Core ["Application Core"]
        Gateway --> Config["Pydantic Settings"]
        Gateway --> Log["Structured Safe Logging"]
        Gateway --> Lifespan["Lifespan Context Manager"]
    end

    subgraph Health ["Health Monitoring"]
        Gateway --> Live["/api/v1/health/live (Process Probe)"]
        Gateway --> Ready["/api/v1/health/ready (Dependency Probe)"]
        Ready --> Svc["HealthService"]
    end

    subgraph Infrastructure ["Persistence & Caching"]
        Svc -->|"Async Query SELECT 1"| PG[("PostgreSQL 16 (or Supabase)")]
        Svc -->|"Async PING"| RD[("Redis 7")]
        Lifespan -->|"Graceful Shutdown"| PG
        Lifespan -->|"Graceful Shutdown"| RD
    end
```

---

## 3. Technology Stack

- **Runtime:** Python 3.12+ (tested on Python 3.13)
- **Web Framework:** FastAPI & Uvicorn
- **Configuration:** Pydantic Settings v2
- **ORM & DB Access:** SQLAlchemy 2.x (asyncio) + asyncpg
- **Database:** PostgreSQL 16 (supports local Docker and Supabase)
- **Caching & State:** Redis 7 + redis-py (asyncio)
- **Migrations:** Alembic
- **Testing:** Pytest, pytest-asyncio, HTTPX
- **Code Quality:** Ruff
- **Containerization:** Docker & Docker Compose

---

## 4. Repository Structure

```text
unified-ai-gateway/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # Application factory, lifespan, CORS & router mounting
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes/
│   │   │       ├── __init__.py        # Router aggregation (/api/v1)
│   │   │       └── health.py          # Liveness and readiness endpoints
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py              # Centralized Pydantic settings & validation
│   │   │   └── logging.py             # Redaction-safe structured logging
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # DeclarativeBase for future models
│   │   │   └── session.py             # Async database & Redis connection managers
│   │   └── services/
│   │       ├── __init__.py
│   │       └── health.py              # Health check business logic (DB & Redis probes)
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── .gitkeep               # Directory for revision scripts
│   │   ├── env.py                     # Async migration runner linked to app settings
│   │   └── script.py.mako             # Revision template
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py                # Pytest async HTTP client fixtures
│   │   ├── test_health.py             # Liveness and readiness probe test suite
│   │   └── test_config.py             # Settings and environment override test suite
│   │
│   ├── alembic.ini                    # Alembic configuration
│   ├── requirements.txt               # Pinned runtime and dev dependencies
│   ├── Dockerfile                     # Multi-stage/slim non-root container image
│   └── pyproject.toml                 # Ruff & Pytest tool configurations
│
├── docker-compose.yml                 # Orchestration for PostgreSQL, Redis, and Backend
├── .env.example                       # Documented environment template
├── .gitignore                         # Standard git exclusion list
└── README.md                          # Documentation
```

---

## 5. Prerequisites

- **Python:** 3.12 or newer
- **Docker Desktop** (optional for local multi-container development)
- **PostgreSQL 16 & Redis 7** (or cloud alternatives such as Supabase and Upstash)

---

## 6. Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Key environment variables:

| Variable | Description | Default |
|---|---|---|
| `APP_NAME` | Name of the service | `Unified AI Gateway` |
| `APP_ENV` | Runtime environment (`development`, `staging`, `production`) | `development` |
| `DEBUG` | Enable debug mode and query logging | `true` |
| `API_V1_PREFIX` | Base prefix for version 1 API endpoints | `/api/v1` |
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://gateway_user:change_this_password@localhost:5432/gateway_db` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `CORS_ORIGINS` | Permitted CORS origins (JSON array or comma-separated) | `["http://localhost:3000","http://localhost:5173"]` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (optional cloud database) | `None` |
| `SUPABASE_SERVICE_ROLE_KEY`| Supabase service role secret key (optional) | `None` |

---

## 7. Running with Docker Compose

To start PostgreSQL, Redis, and the FastAPI backend simultaneously:

```bash
# Build and start all services in the background
docker compose up --build -d

# Check running service status
docker compose ps

# Follow application logs
docker compose logs -f backend

# Stop all containers
docker compose down
```

The gateway backend will be accessible at:
- **API Base:** `http://localhost:8000`
- **Swagger Docs:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## 8. Running Locally Without Docker

### 1. Create and Activate a Virtual Environment

```bash
cd backend
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the FastAPI Application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 9. Running Database Migrations

Alembic is configured to run asynchronously using settings directly from `.env`.

```bash
cd backend

# View current migration status
alembic current

# Create a new revision when models are added (Phase 2+)
alembic revision --autogenerate -m "create_initial_models"

# Apply pending migrations to the database
alembic upgrade head

# Rollback the last migration
alembic downgrade -1
```

---

## 10. API Endpoints

### Liveness Probe

- **Endpoint:** `GET /api/v1/health/live`
- **Purpose:** Verifies that the HTTP server process is running. Used by Kubernetes/Docker for process liveness.
- **Dependencies:** None.
- **Response (HTTP 200):**
  ```json
  {
    "status": "alive",
    "service": "unified-ai-gateway"
  }
  ```

### Readiness Probe

- **Endpoint:** `GET /api/v1/health/ready`
- **Purpose:** Independently verifies connectivity to PostgreSQL (via `SELECT 1`) and Redis (via `ping()`).
- **Response when Healthy (HTTP 200):**
  ```json
  {
    "status": "ready",
    "checks": {
      "database": "connected",
      "redis": "connected"
    }
  }
  ```
- **Response when Degraded (HTTP 503 Service Unavailable):**
  ```json
  {
    "status": "unhealthy",
    "checks": {
      "database": "disconnected",
      "redis": "connected"
    }
  }
  ```

---

## 11. Automated Testing & Code Quality

### Running the Automated Test Suite

The test suite tests liveness, readiness under all dependency state combinations, and configuration validation without requiring a live database or Redis instance:

```bash
cd backend
pytest
```

To run with verbose output:
```bash
pytest -v -s
```

### Linting and Formatting with Ruff

```bash
cd backend

# Check linting rules
ruff check .

# Check formatting
ruff format --check .
```

---

## 12. Troubleshooting Common Issues

1. **`asyncpg.exceptions.InvalidPasswordError` or Connection Refused on Database:**
   - Verify PostgreSQL is running on port 5432 or that your connection string in `.env` matches your credentials.
   - For Docker containers, ensure the host in `DATABASE_URL` is `db` rather than `localhost`.

2. **Redis Connection Failures:**
   - Verify Redis is running on port 6379 (`redis-cli ping` should return `PONG`).
   - For Docker containers, ensure `REDIS_URL` uses `redis://redis:6379/0`.

3. **Supabase Direct Connection on IPv4 Networks:**
   - Supabase direct database endpoints (`db.[project-ref].supabase.co`) only provide IPv6 addresses.
   - For IPv4-only networks, connect via the Supabase connection pooler (`aws-0-[region].pooler.supabase.com:6543/postgres`).
