"""add hybrid matching scores

Revision ID: 0004_matching_engine
Revises: 0003_job_intelligence
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_matching_engine"
down_revision: str | None = "0003_job_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_score", sa.Float(), nullable=False),
        sa.Column("skill_score", sa.Float(), nullable=False),
        sa.Column("education_score", sa.Float(), nullable=False),
        sa.Column("experience_score", sa.Float(), nullable=False),
        sa.Column("location_score", sa.Float(), nullable=False),
        sa.Column("preference_score", sa.Float(), nullable=False),
        sa.Column("llm_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("rules_passed", sa.Boolean(), nullable=False),
        sa.Column("rule_reasons", sa.JSON(), nullable=False),
        sa.Column("matched_skills", sa.JSON(), nullable=False),
        sa.Column("missing_skills", sa.JSON(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("resume_evidence", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.String(length=30), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("score_version", sa.String(length=50), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_scores_job_id", "job_scores", ["job_id"])
    op.create_index("ix_job_scores_resume_id", "job_scores", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_job_scores_resume_id", table_name="job_scores")
    op.drop_index("ix_job_scores_job_id", table_name="job_scores")
    op.drop_table("job_scores")
