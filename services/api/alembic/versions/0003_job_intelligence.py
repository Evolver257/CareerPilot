"""add structured job skills

Revision ID: 0003_job_intelligence
Revises: 0002_resume_intelligence
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_job_intelligence"
down_revision: str | None = "0002_resume_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("skill_type", sa.String(length=30), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "skill_name", "skill_type", name="uq_job_skills_name_type"),
    )
    op.create_index("ix_job_skills_job_id", "job_skills", ["job_id"])
    op.create_index("ix_job_skills_skill_name", "job_skills", ["skill_name"])
    op.create_index("ix_job_skills_skill_type", "job_skills", ["skill_type"])


def downgrade() -> None:
    op.drop_index("ix_job_skills_skill_type", table_name="job_skills")
    op.drop_index("ix_job_skills_skill_name", table_name="job_skills")
    op.drop_index("ix_job_skills_job_id", table_name="job_skills")
    op.drop_table("job_skills")
