# Architecture

CareerPilot is a monorepo with explicit boundaries between the web application, API, domain packages, platform adapters, and infrastructure.

```text
apps/web
    │ REST / future SSE
services/api ── services/worker
    │
SQLAlchemy repositories and domain services
    │
PostgreSQL / Redis
```

The API owns HTTP concerns and dependency injection. Repositories own persistence queries. Services own business rules. Platform adapters and agent tools will be added behind package interfaces in later phases.

Phase 1 keeps the model intentionally small: users, preferences, resumes, companies, and jobs. Job scoring and application state are not mixed into the foundation until their state machines and audit events are defined.
