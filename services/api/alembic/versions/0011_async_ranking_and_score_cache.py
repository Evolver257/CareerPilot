"""add persisted asynchronous ranking runs and score cache metadata

Revision ID: 0011_async_ranking_cache
Revises: 0010_persist_llm_active_provider
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0011_async_ranking_cache"
down_revision: str | None = "0010_persist_llm_active_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_scores",
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "job_scores",
        sa.Column("judge_source", sa.String(length=30), server_default="llm", nullable=False),
    )
    op.create_index(
        "ix_job_scores_input_fingerprint",
        "job_scores",
        ["input_fingerprint"],
        unique=False,
    )

    op.create_table(
        "ranking_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("processed_candidates", sa.Integer(), nullable=False),
        sa.Column("total_candidates", sa.Integer(), nullable=False),
        sa.Column("cache_hits", sa.Integer(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("fallback_count", sa.Integer(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ranking_runs_resume_id", "ranking_runs", ["resume_id"], unique=False)
    op.create_index("ix_ranking_runs_status", "ranking_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ranking_runs_status", table_name="ranking_runs")
    op.drop_index("ix_ranking_runs_resume_id", table_name="ranking_runs")
    op.drop_table("ranking_runs")
    op.drop_index("ix_job_scores_input_fingerprint", table_name="job_scores")
    op.drop_column("job_scores", "judge_source")
    op.drop_column("job_scores", "input_fingerprint")
