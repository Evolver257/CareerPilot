# Phase 0 Repository Audit

Audit date: 2026-08-24

## Current Architecture

The workspace was empty apart from the generated `work/` and `outputs/` directories. There was no existing application, package manager configuration, Python dependency file, database schema, Docker configuration, or Git-managed feature code to migrate.

Phase 1 therefore initializes a new monorepo with:

- `apps/web`: Next.js, React, TypeScript, Tailwind, and skeleton pages
- `services/api`: FastAPI, Pydantic, SQLAlchemy 2, Alembic, and API tests
- `services/worker`: Redis-connected worker placeholder
- `packages/*`: explicit future boundaries for agent, intelligence, RAG, browser, LLM, platform, and shared contracts
- `infra/*`: infrastructure documentation and the root Compose entrypoint

## Reusable Components

No existing components were available. The new foundation intentionally keeps repositories, services, routers, and platform boundaries separate so later phases can add functionality without coupling core business logic to a recruitment website.

## Technical Debt

- Authentication and authorization are not part of Phase 1.
- Resume upload/parsing, pgvector retrieval, matching, Campaign state, Agent Runtime, and Browser Agent are not implemented yet.
- The worker is a readiness placeholder; queue semantics will be added with Campaign/Agent phases.
- The Compose PostgreSQL image is `pgvector/pgvector:pg16` so the local stack is ready for the next phase, but no vector column or extension-specific query is used yet.
- The local machine already had port 8000 occupied during verification; Compose supports an `API_PORT` override.

## Migration Plan

There was no legacy code to migrate. The initial migration creates User, UserPreference, Resume, Company, and Job. Later phases should add new revisions incrementally and preserve the adapter/service/repository boundaries established here.
