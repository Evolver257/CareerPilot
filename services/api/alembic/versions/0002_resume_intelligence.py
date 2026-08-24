"""add resume chunks and embeddings

Revision ID: 0002_resume_intelligence
Revises: 0001_foundation
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.embedding import EmbeddingType

revision: str = "0002_resume_intelligence"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "resume_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("embedding", EmbeddingType(384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_chunks_resume_id", "resume_chunks", ["resume_id"])
    op.create_index("ix_resume_chunks_chunk_type", "resume_chunks", ["chunk_type"])


def downgrade() -> None:
    op.drop_index("ix_resume_chunks_chunk_type", table_name="resume_chunks")
    op.drop_index("ix_resume_chunks_resume_id", table_name="resume_chunks")
    op.drop_table("resume_chunks")
