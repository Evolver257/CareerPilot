# CareerPilot

CareerPilot is an extensible AI job-search platform foundation. Phase 1 established the web/API/database boundary, Phase 2 added Resume Intelligence, Phase 3 added Job Intelligence, Phase 4 added hybrid Resume–JD matching with Resume RAG, and Phase 5 adds cost-aware multi-stage ranking.

## Current status

Phase 0 (repository audit) through Phase 5 (Ranking Pipeline) are implemented:

- Next.js web workspace for Dashboard, Jobs, Job Detail, and Resume upload/Profile/Chunks
- FastAPI application with `/health`, Jobs read endpoints, and Resume Intelligence APIs
- Async SQLAlchemy 2 data layer with PostgreSQL in development
- Alembic migrations for the foundation entities and `resume_chunks` with pgvector embeddings
- PDF, DOCX, Markdown, and TXT parsing with raw-text preservation and heuristic structured extraction
- Provider interface plus deterministic `MockLLMProvider` embeddings for local development without API keys
- Job Parser, Normalizer, Skill/Requirement Extractors, and content-hash/platform-key deduplication
- 30-entry Mock JD dataset with structured import and per-job analysis endpoints
- Configurable hybrid scoring across semantic, skill, education, experience, location, preference, and LLM Judge signals
- Resume RAG retrieval and reranking that supplies only relevant chunks to the Judge
- Rule Filter → Embedding Rank → Reranker → LLM Judge → Final Ranking pipeline
- Configurable stage limits with full candidate-level Trace and a dedicated Ranking workspace
- Redis and a worker placeholder in Docker Compose
- API parser/upload/chunk tests, migration test, frontend typecheck, lint, and production build

## Architecture

```text
Next.js Web  ── REST ──>  FastAPI API  ──>  SQLAlchemy 2  ──> PostgreSQL
       │                       │
       │                       └──────────────> Redis / Worker
       │
       └── future SSE/WebSocket boundary for Agent and Extension
```

The domain layer does not depend on a specific recruitment website. Future platform-specific behavior belongs behind `JobPlatformAdapter` in `packages/platforms`.

## Quick start

Prerequisites: Docker Desktop, Python 3.12+, and Node.js 20+.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Then open:

- Web: http://localhost:3000/dashboard
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

If port 8000 is already in use, start the API on another host port while keeping the container port unchanged:

```powershell
$env:API_PORT = "8001"
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8001"
docker compose up --build
```

For local development without Docker:

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```powershell
cd apps/web
npm install
npm run dev
```

## Security and platform usage notice

CareerPilot does not upload recruitment-site cookies, passwords, or authentication tokens. Any future browser integration must pause for CAPTCHA, login, risk-control, platform-limit, or unknown-page conditions and request user action. No bypass or evasion behavior is part of this project.

## Roadmap

1. Foundation (current)
2. ~~Resume Intelligence and pgvector~~
3. ~~Job Intelligence and Mock Jobs~~
4. ~~Hybrid matching and Resume RAG~~
5. ~~Ranking pipeline~~
6. Campaign and application state machine
7. Agent runtime
8. Browser Agent and Mock Platform

See [docs/phase-0-audit.md](docs/phase-0-audit.md), [docs/architecture.md](docs/architecture.md), and [docs/development.md](docs/development.md) for implementation notes.
