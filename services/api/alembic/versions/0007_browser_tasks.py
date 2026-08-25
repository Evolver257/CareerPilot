"""add browser tasks and extension events

Revision ID: 0007_browser_tasks
Revises: 0006_agent_runtime
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_browser_tasks"
down_revision: str | None = "0006_agent_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("scenario", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("current_action", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("action_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_tasks_application_id", "browser_tasks", ["application_id"])
    op.create_index("ix_browser_tasks_campaign_id", "browser_tasks", ["campaign_id"])
    op.create_index("ix_browser_tasks_platform", "browser_tasks", ["platform"])
    op.create_index("ix_browser_tasks_status", "browser_tasks", ["status"])
    op.create_index("ix_browser_tasks_user_id", "browser_tasks", ["user_id"])

    op.create_table(
        "browser_task_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("action_id", sa.String(length=100), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["browser_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_task_events_event_type", "browser_task_events", ["event_type"])
    op.create_index("ix_browser_task_events_task_id", "browser_task_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_browser_task_events_task_id", table_name="browser_task_events")
    op.drop_index("ix_browser_task_events_event_type", table_name="browser_task_events")
    op.drop_table("browser_task_events")
    op.drop_index("ix_browser_tasks_user_id", table_name="browser_tasks")
    op.drop_index("ix_browser_tasks_status", table_name="browser_tasks")
    op.drop_index("ix_browser_tasks_platform", table_name="browser_tasks")
    op.drop_index("ix_browser_tasks_campaign_id", table_name="browser_tasks")
    op.drop_index("ix_browser_tasks_application_id", table_name="browser_tasks")
    op.drop_table("browser_tasks")
