# Architecture

CareerPilot is a monorepo with explicit boundaries between the web application, API, domain packages, platform adapters, and infrastructure.

![Phase 10 architecture](assets/architecture.svg)

```text
apps/web
    │ REST / future SSE
services/api ── services/worker
    │
SQLAlchemy repositories and domain services
    │
PostgreSQL / Redis
```

The API owns HTTP concerns and dependency injection. Repositories own persistence queries. Services own business rules. The Dashboard uses a read-only analytics service, while Platform Adapters and Agent Tools remain behind package interfaces. The platform layer now contains Mock, CareerBoard, and a BOSS visible-page adapter; BOSS DOM assumptions remain isolated from Campaign and Agent Runtime services.

Phase 1 keeps the model intentionally small: users, preferences, resumes, companies, and jobs. Job scoring and application state are not mixed into the foundation until their state machines and audit events are defined.
