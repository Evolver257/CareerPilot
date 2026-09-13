"""Bind collected jobs to the Career Advisor conversation that requested them."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_career_advisor_session_jobs"
down_revision: str | None = "0032_memory_restore_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "career_advisor_session_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=40),
            nullable=False,
            server_default="automated_collection",
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("first_linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["career_advisor_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["career_advisor_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "job_id",
            name="uq_career_advisor_session_jobs_session_job",
        ),
    )
    op.create_index(
        "ix_career_advisor_session_jobs_job_id",
        "career_advisor_session_jobs",
        ["job_id"],
    )
    op.create_index(
        "ix_career_advisor_session_jobs_session_id",
        "career_advisor_session_jobs",
        ["session_id"],
    )
    op.create_index(
        "ix_career_advisor_session_jobs_source_message_id",
        "career_advisor_session_jobs",
        ["source_message_id"],
    )
    op.create_index(
        "ix_career_advisor_session_jobs_source_type",
        "career_advisor_session_jobs",
        ["source_type"],
    )
    op.create_index(
        "ix_career_advisor_session_jobs_session_last_linked",
        "career_advisor_session_jobs",
        ["session_id", "last_linked_at"],
    )


def downgrade() -> None:
    op.drop_table("career_advisor_session_jobs")
