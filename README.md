# Unified AI Gateway

A centralized, scalable API gateway designed for routing, managing, and observing interactions across multiple AI and LLM providers.

## Project Structure

```
unified-ai-gateway/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       └── health.py
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── session.py
│   │   │
│   │   └── services/
│   │       ├── __init__.py
│   │       └── health.py
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── .gitkeep
│   │   ├── env.py
│   │   └── script.py.mako
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_health.py
│   │   └── test_config.py
│   │
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── Dockerfile
│   └── pyproject.toml
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Quick Start

### 1. Environment Setup

Copy `.env.example` to `.env` and adjust the variables as needed:

```bash
cp .env.example .env
```

### 2. Run with Docker Compose

```bash
docker compose up --build
```

The gateway will be accessible at `http://localhost:8000` and interactive API docs at `http://localhost:8000/docs`.

### 3. Local Development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 4. Running Tests

```bash
cd backend
pytest
```
