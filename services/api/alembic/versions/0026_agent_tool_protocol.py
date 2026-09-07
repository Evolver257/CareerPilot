"""Add durable provider-neutral Agent tool invocations."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_agent_tool_protocol"
down_revision: str | None = "0025_quick_matching_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("call_id", sa.String(length=300), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("parent_call_id", sa.String(length=300), nullable=True),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("server_id", sa.String(length=200), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "call_id", name="uq_agent_tool_invocations_run_call"),
        sa.UniqueConstraint(
            "run_id",
            "idempotency_key",
            "attempt",
            name="uq_agent_tool_invocations_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_tool_invocations_run_id", "agent_tool_invocations", ["run_id"]
    )
    op.create_index(
        "ix_agent_tool_invocations_step_id", "agent_tool_invocations", ["step_id"]
    )
    op.create_index(
        "ix_agent_tool_invocations_idempotency_key",
        "agent_tool_invocations",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_agent_tool_invocations_tool_name", "agent_tool_invocations", ["tool_name"]
    )
    op.create_index(
        "ix_agent_tool_invocations_source", "agent_tool_invocations", ["source"]
    )
    op.create_index(
        "ix_agent_tool_invocations_server_id", "agent_tool_invocations", ["server_id"]
    )
    op.create_index(
        "ix_agent_tool_invocations_status", "agent_tool_invocations", ["status"]
    )


def downgrade() -> None:
    for name in [
        "ix_agent_tool_invocations_status",
        "ix_agent_tool_invocations_server_id",
        "ix_agent_tool_invocations_source",
        "ix_agent_tool_invocations_tool_name",
        "ix_agent_tool_invocations_idempotency_key",
        "ix_agent_tool_invocations_step_id",
        "ix_agent_tool_invocations_run_id",
    ]:
        op.drop_index(name, table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")
