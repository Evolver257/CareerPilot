# Development

## Backend

From `services/api`:

```powershell
pip install -e ".[dev]"
python -m alembic upgrade head
pytest
```

Phase 2 Resume Intelligence exposes:

```text
POST /api/resumes                 multipart upload and parse
POST /api/resumes/{id}/parse      regenerate Profile and chunks
GET  /api/resumes                 list stored resumes
GET  /api/resumes/{id}            raw text and structured Profile
GET  /api/resumes/{id}/chunks     semantic chunks and embedding dimensions
```

Supported files are PDF, DOCX, Markdown, and UTF-8 TXT. The default local
provider creates deterministic 384-dimensional hash embeddings, so no LLM key
is required for development. PostgreSQL uses pgvector; SQLite uses JSON only
for local tests.

Phase 3 Job Intelligence exposes:

```text
POST /api/jobs/import             import one raw JD or Mock JDs
POST /api/jobs/{id}/analyze       extract structured job, skills, and requirements
```

Single JD import example:

```json
{
  "mode": "single",
  "platform": "manual",
  "raw_jd": "Senior Backend Engineer\n\nRequirements\n- Python and FastAPI..."
}
```

Mock dataset import example:

```json
{
  "mode": "mock",
  "limit": 30
}
```

Job skills are persisted in `job_skills` with `required`, `preferred`, or
`optional` classification. The complete structured analysis remains in
`jobs.normalized_data` for later matching and ranking phases.

## Frontend

From `apps/web`:

```powershell
npm install
npm run typecheck
npm run lint
npm run build
```

## Docker

From the repository root:

```powershell
docker compose up --build
```

The API container runs the Alembic migration before starting FastAPI. PostgreSQL and Redis data are stored in named Docker volumes.
