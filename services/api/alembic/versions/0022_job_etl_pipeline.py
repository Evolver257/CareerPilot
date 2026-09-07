"""Add raw job snapshots and ETL quality/lifecycle metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_job_etl_pipeline"
down_revision: str | None = "0021_background_work_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lifecycle_status", sa.String(length=30), nullable=True))
    op.add_column("jobs", sa.Column("data_quality_score", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("data_quality_level", sa.String(length=20), nullable=True))
    op.add_column("jobs", sa.Column("duplicate_group_id", sa.String(length=128), nullable=True))
    op.execute(sa.text("UPDATE jobs SET lifecycle_status = 'active' WHERE lifecycle_status IS NULL"))
    op.execute(sa.text("UPDATE jobs SET data_quality_level = 'unknown' WHERE data_quality_level IS NULL"))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("lifecycle_status", nullable=False, server_default="active")
        batch_op.alter_column("data_quality_level", nullable=False, server_default="unknown")
    op.create_index("ix_jobs_lifecycle_status", "jobs", ["lifecycle_status"])
    op.create_index("ix_jobs_data_quality_score", "jobs", ["data_quality_score"])
    op.create_index("ix_jobs_data_quality_level", "jobs", ["data_quality_level"])
    op.create_index("ix_jobs_duplicate_group_id", "jobs", ["duplicate_group_id"])
    op.create_table(
        "job_raw_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("source_platform", sa.String(length=100), nullable=False),
        sa.Column("external_job_id", sa.String(length=300), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("raw_title", sa.String(length=300), nullable=False),
        sa.Column("raw_salary", sa.String(length=300), nullable=True),
        sa.Column("raw_location", sa.String(length=300), nullable=True),
        sa.Column("description_html", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_job_raw_snapshots_job_hash"),
    )
    op.create_index("ix_job_raw_snapshots_job_id", "job_raw_snapshots", ["job_id"])
    op.create_index("ix_job_raw_snapshots_source_platform", "job_raw_snapshots", ["source_platform"])
    op.create_index("ix_job_raw_snapshots_external_job_id", "job_raw_snapshots", ["external_job_id"])
    op.create_index("ix_job_raw_snapshots_content_hash", "job_raw_snapshots", ["content_hash"])
    op.create_index("ix_job_raw_snapshots_collected_at", "job_raw_snapshots", ["collected_at"])


def downgrade() -> None:
    op.drop_index("ix_job_raw_snapshots_collected_at", table_name="job_raw_snapshots")
    op.drop_index("ix_job_raw_snapshots_content_hash", table_name="job_raw_snapshots")
    op.drop_index("ix_job_raw_snapshots_external_job_id", table_name="job_raw_snapshots")
    op.drop_index("ix_job_raw_snapshots_source_platform", table_name="job_raw_snapshots")
    op.drop_index("ix_job_raw_snapshots_job_id", table_name="job_raw_snapshots")
    op.drop_table("job_raw_snapshots")
    op.drop_index("ix_jobs_duplicate_group_id", table_name="jobs")
    op.drop_index("ix_jobs_data_quality_level", table_name="jobs")
    op.drop_index("ix_jobs_data_quality_score", table_name="jobs")
    op.drop_index("ix_jobs_lifecycle_status", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("duplicate_group_id")
        batch_op.drop_column("data_quality_level")
        batch_op.drop_column("data_quality_score")
        batch_op.drop_column("lifecycle_status")
