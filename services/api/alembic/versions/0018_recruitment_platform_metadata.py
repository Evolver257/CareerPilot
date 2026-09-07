"""add platform metadata and cross-platform job fingerprints

Revision ID: 0018_recruitment_platform_metadata
Revises: 0017_job_freshness
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_platform_metadata"
down_revision: str | None = "0017_job_freshness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("platform_metadata", sa.JSON(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("job_fingerprint", sa.String(length=128), nullable=True),
    )
    op.execute(sa.text("UPDATE jobs SET platform_metadata = '{}' WHERE platform_metadata IS NULL"))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("platform_metadata", nullable=False)
        batch_op.drop_constraint("uq_jobs_content_hash", type_="unique")
    op.create_index("ix_jobs_job_fingerprint", "jobs", ["job_fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_jobs_job_fingerprint", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("job_fingerprint")
        batch_op.drop_column("platform_metadata")
        batch_op.create_unique_constraint("uq_jobs_content_hash", ["content_hash"])
