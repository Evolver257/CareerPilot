"""Migrate semantic vectors from MiniLM 384d to Qwen3 1024d.

The old vectors cannot be reused after changing models.  They are cleared as
part of the type change so the subsequent knowledge/resume backfill cannot
accidentally mix vector spaces.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_qwen3_embedding_dimensions"
down_revision: str | None = "0022_job_etl_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _resize_vectors(dimensions: int) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite test databases store embeddings as JSON and do not have a
        # vector typmod to migrate.
        return

    # A 384-dimensional value cannot be cast to vector(1024).  Clear before
    # changing the typmod; the durable backfill will repopulate every vector.
    op.execute(sa.text("UPDATE resume_chunks SET embedding = NULL"))
    op.execute(sa.text("UPDATE job_knowledge_chunks SET embedding = NULL"))
    op.execute(
        sa.text(
            "UPDATE job_knowledge_chunks "
            "SET embedding_dimensions = 0 WHERE embedding_dimensions IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE resume_chunks "
            f"ALTER COLUMN embedding TYPE vector({dimensions}) USING NULL::vector"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE job_knowledge_chunks "
            f"ALTER COLUMN embedding TYPE vector({dimensions}) USING NULL::vector"
        )
    )


def upgrade() -> None:
    _resize_vectors(1024)


def downgrade() -> None:
    _resize_vectors(384)
