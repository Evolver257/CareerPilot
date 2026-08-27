# CareerPilot

CareerPilot is an extensible AI job-search platform foundation. Phase 1 established the web/API/database boundary, Phase 2 added Resume Intelligence, Phase 3 added Job Intelligence, Phase 4 added hybrid Resume–JD matching with Resume RAG, Phase 5 added cost-aware multi-stage ranking, Phase 6 added resumable application campaigns, Phase 7 added a traceable Agent Runtime, Phase 8 added a Browser Agent boundary with a Mock Platform, Phase 9 added safe user-session adapters for CareerBoard and BOSS 直聘 visible-page compatibility, and Phase 10 productizes the Dashboard, funnel, trace, usage, retry, and error surfaces.

## Current status

Phase 0 (repository audit) through Phase 10 (Productization) are implemented:

- Next.js web workspace for Dashboard, Jobs, Job Detail, and Resume upload/Profile/Chunks
- FastAPI application with `/health`, Jobs read endpoints, and Resume Intelligence APIs
- Async SQLAlchemy 2 data layer with PostgreSQL in development
- Alembic migrations for the foundation entities and `resume_chunks` with pgvector embeddings
- PDF, DOCX, Markdown, and TXT parsing with raw-text preservation and heuristic structured extraction
- Provider interface plus deterministic Chinese-aware local embeddings, with optional OpenAI-compatible `/embeddings` support
- Job Parser, Normalizer, Skill/Requirement Extractors, and content-hash/platform-key deduplication
- 30-entry Mock JD dataset with structured import and per-job analysis endpoints
- Configurable hybrid scoring across semantic, skill, education, experience, location, preference, and LLM Judge signals
- Resume RAG retrieval and reranking that supplies only relevant chunks to the Judge
- Rule Filter → Embedding Rank → Reranker → LLM Judge → Final Ranking pipeline
- Configurable stage limits with full candidate-level Trace and a dedicated Ranking workspace
- Campaign, CampaignJob, and Application persistence with explicit state transitions
- Human approval, application queuing, pause/resume/cancel, retry, and state-history tracking
- Single-Orchestrator Agent Runtime with Planner, Executor, Tool Registry, state, and memory checkpoints
- Nine schema-validated job-search tools with retry, timeout, max-step, pause/resume, and cancel controls
- Persistent AgentRun, AgentStep, and AgentEvent trace plus SSE event streaming
- Agent Runs workspace with expandable Tool Input/Output, status, latency, and approval controls
- BrowserTask persistence with structured NAVIGATE/CLICK/TYPE/EXTRACT/CHECK_STATE actions and auditable events
- WXT Browser Extension boundary over WebSocket with semantic DOM actions and no credential transfer
- Mock Platform job list/detail/apply pages plus SUCCESS, CAPTCHA_REQUIRED, LOGIN_REQUIRED, PLATFORM_LIMIT, and DOM_CHANGED scenarios
- Browser Task console with Extension connection status, human-action pause/resume, and Mock Extension CI harness
- Independent CareerBoard adapter directory with selectors, parser, detector, actions, adapter registry, and local fixture validation
- BOSS 直聘 visible-page adapter with in-page extension dispatch, structured import, exact candidate approval, deduplication, and user-approved BrowserTask submission
- CAPTCHA, LOGIN_REQUIRED, RISK_CONTROL, and UNKNOWN_STATE detection that pauses the task and emits REQUEST_USER_ACTION
- Recoverable CareerBoard BrowserTask flow with adapter failure recognition and DOM-change regression tests
- Product Dashboard with statistics, Application Funnel, Agent Trace quality, LLM token usage, and explicit cost status
- LLM 设置入口，支持 OpenAI Chat Completions 与 Anthropic Messages 格式；用户 key 服务端加密持久化、脱敏展示与不落库连接测试
- Bounded terminal Agent Retry that creates a new auditable Run linked by `retry_of`
- Productization architecture diagram, real local-page Demo GIF, screenshots, technical highlights, and interview talking points
- Redis and a worker placeholder in Docker Compose
- API parser/upload/chunk tests, migration test, frontend typecheck, lint, and production build

## Architecture

```text
Next.js Web  ── REST/SSE ──>  FastAPI API  ──>  SQLAlchemy 2  ──> PostgreSQL
       │                       │
       │                       └──────────────> Redis / Worker
       │
       └── future SSE/WebSocket boundary for Agent and Extension
```

The domain layer does not depend on a specific recruitment website. Platform-specific behavior belongs behind `JobPlatformAdapter` in `services/api/app/platforms`, with each adapter isolated in its own directory.

## Quick start

Prerequisites: Docker Desktop, Python 3.12+, and Node.js 20+.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Then open:

- Web: http://localhost:3000/dashboard
- API docs: http://localhost:8010/docs
- Health: http://localhost:8010/health
- Agent Runs: http://localhost:3000/agent-runs
- Browser Tasks: http://localhost:3000/browser-tasks
- Mock Platform: http://localhost:3000/mock-platform
- Product Dashboard: http://localhost:3000/dashboard
- LLM 设置: http://localhost:3000/settings

The default API host port is 8010 to avoid conflicts with common local services. If another port is needed, start the API on another host port while keeping the container port unchanged:

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

CareerPilot does not upload recruitment-site cookies, passwords, authentication tokens, or raw page HTML. BOSS compatibility only captures structured fields from the user's currently visible page through the browser extension; it does not run a background crawler or call undocumented APIs. Applications require a user-approved BrowserTask in the user's own session. Any browser integration pauses for CAPTCHA, login, risk-control, platform-limit, DOM-change, or unknown-page conditions and requests user action. No bypass, evasion, or unattended bulk submission is part of this project.

LLM API keys can be entered from `/settings`. They are encrypted at rest by the API service and only a four-character hint is returned to the web app. The connection test makes one minimal generation request without saving or changing the configuration. Set `LLM_ENCRYPTION_KEY` to a long random secret in any non-development deployment, and never commit provider keys to the repository. The default provider remains the local Mock provider until a user explicitly saves and enables a remote provider.

Semantic embeddings are configured independently from the LLM judge. The default `mock-hash-384-v2` mode is local and requires no key. To use an OpenAI-compatible embedding endpoint, set `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_API_KEY`, and optionally `EMBEDDING_BASE_URL`. Existing resume chunks are automatically re-embedded when their persisted embedding signature changes.

## Roadmap

1. Foundation (current)
2. ~~Resume Intelligence and pgvector~~
3. ~~Job Intelligence and Mock Jobs~~
4. ~~Hybrid matching and Resume RAG~~
5. ~~Ranking pipeline~~
6. ~~Campaign and application state machine~~
7. ~~Agent runtime~~
8. ~~Browser Agent and Mock Platform~~
9. ~~Platform Adapter Prototype + BOSS visible-page compatibility~~
10. ~~Productization~~

See [docs/phase-0-audit.md](docs/phase-0-audit.md), [docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md), [docs/boss-zhipin-adapter.md](docs/boss-zhipin-adapter.md), and [docs/phase-10-productization.md](docs/phase-10-productization.md) for implementation notes.
