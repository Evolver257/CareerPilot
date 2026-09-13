"""Add durable long-term-memory embedding backfill runs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031_memory_embedding_runs"
down_revision: str | None = "0030_agent_memory_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_embedding_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("current_memory_id", sa.Uuid(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_memory_id"], ["agent_memories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_embedding_runs_user_id", "memory_embedding_runs", ["user_id"])
    op.create_index("ix_memory_embedding_runs_mode", "memory_embedding_runs", ["mode"])
    op.create_index("ix_memory_embedding_runs_status", "memory_embedding_runs", ["status"])
    op.create_index(
        "ix_memory_embedding_runs_current_memory_id",
        "memory_embedding_runs",
        ["current_memory_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embedding_runs_current_memory_id", table_name="memory_embedding_runs")
    op.drop_index("ix_memory_embedding_runs_status", table_name="memory_embedding_runs")
    op.drop_index("ix_memory_embedding_runs_mode", table_name="memory_embedding_runs")
    op.drop_index("ix_memory_embedding_runs_user_id", table_name="memory_embedding_runs")
    op.drop_table("memory_embedding_runs")
