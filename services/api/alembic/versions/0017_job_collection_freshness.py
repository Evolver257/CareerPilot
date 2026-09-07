"""track the latest job collection time

Revision ID: 0017_job_freshness
Revises: 0016_career_advisor_chat
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_job_freshness"
down_revision: str | None = "0016_career_advisor_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing records do not have a trustworthy capture timestamp. Their
    # creation time is the conservative approximation; seeing the same job in
    # a later collection refreshes this field precisely.
    op.execute(
        "UPDATE jobs SET last_collected_at = COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)"
    )
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("last_collected_at", nullable=False)
    op.create_index("ix_jobs_last_collected_at", "jobs", ["last_collected_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_last_collected_at", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("last_collected_at")
