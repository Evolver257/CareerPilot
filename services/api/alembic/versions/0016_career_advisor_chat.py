"""add persistent Career Advisor sessions, messages, and citations

Revision ID: 0016_career_advisor_chat
Revises: 0015_knowledge_fts
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_career_advisor_chat"
down_revision: str | None = "0015_knowledge_fts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "career_advisor_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("context_filters", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_career_advisor_sessions_user_id", "career_advisor_sessions", ["user_id"])
    op.create_index(
        "ix_career_advisor_sessions_resume_id", "career_advisor_sessions", ["resume_id"]
    )

    op.create_table(
        "career_advisor_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("model_provider", sa.String(length=50), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("tool_trace", sa.JSON(), nullable=False),
        sa.Column("answer_metadata", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["career_advisor_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_career_advisor_messages_session_id", "career_advisor_messages", ["session_id"])
    op.create_index("ix_career_advisor_messages_role", "career_advisor_messages", ["role"])
    op.create_index("ix_career_advisor_messages_status", "career_advisor_messages", ["status"])
    op.create_index("ix_career_advisor_messages_intent", "career_advisor_messages", ["intent"])

    op.create_table(
        "career_advisor_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["career_advisor_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["job_knowledge_chunks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "citation_index",
            name="uq_career_advisor_citations_message_index",
        ),
    )
    op.create_index("ix_career_advisor_citations_message_id", "career_advisor_citations", ["message_id"])
    op.create_index("ix_career_advisor_citations_job_id", "career_advisor_citations", ["job_id"])
    op.create_index("ix_career_advisor_citations_chunk_id", "career_advisor_citations", ["chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_career_advisor_citations_chunk_id", table_name="career_advisor_citations")
    op.drop_index("ix_career_advisor_citations_job_id", table_name="career_advisor_citations")
    op.drop_index("ix_career_advisor_citations_message_id", table_name="career_advisor_citations")
    op.drop_table("career_advisor_citations")

    op.drop_index("ix_career_advisor_messages_intent", table_name="career_advisor_messages")
    op.drop_index("ix_career_advisor_messages_status", table_name="career_advisor_messages")
    op.drop_index("ix_career_advisor_messages_role", table_name="career_advisor_messages")
    op.drop_index("ix_career_advisor_messages_session_id", table_name="career_advisor_messages")
    op.drop_table("career_advisor_messages")

    op.drop_index("ix_career_advisor_sessions_resume_id", table_name="career_advisor_sessions")
    op.drop_index("ix_career_advisor_sessions_user_id", table_name="career_advisor_sessions")
    op.drop_table("career_advisor_sessions")
