"""add PostgreSQL full-text indexes for job knowledge retrieval

Revision ID: 0015_job_knowledge_search_indexes
Revises: 0014_job_knowledge_base
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_knowledge_fts"
down_revision: str | None = "0014_job_knowledge_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_knowledge_chunks_content_fts "
        "ON job_knowledge_chunks USING gin "
        "(to_tsvector('simple', content))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_title_description_fts "
        "ON jobs USING gin "
        "(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '')))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_jobs_title_description_fts")
    op.execute("DROP INDEX IF EXISTS ix_job_knowledge_chunks_content_fts")
