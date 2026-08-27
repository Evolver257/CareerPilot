"""add persistent asynchronous market insight reports

Revision ID: 0013_market_insight_reports
Revises: 0012_campaign_async_ranking
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_market_insight_reports"
down_revision: str | None = "0012_campaign_async_ranking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_insight_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="fast"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("stage", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="insufficient"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("source_job_ids", sa.JSON(), nullable=False),
        sa.Column("llm_source", sa.String(length=30), nullable=False, server_default="deterministic"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_insight_reports_user_id", "market_insight_reports", ["user_id"])
    op.create_index("ix_market_insight_reports_query", "market_insight_reports", ["query"])
    op.create_index("ix_market_insight_reports_status", "market_insight_reports", ["status"])
    op.create_index(
        "ix_market_insight_reports_fingerprint", "market_insight_reports", ["fingerprint"]
    )


def downgrade() -> None:
    op.drop_table("market_insight_reports")
