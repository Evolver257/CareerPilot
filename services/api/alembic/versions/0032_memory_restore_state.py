"""Preserve a memory's lifecycle state while it is in the recycle bin."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_memory_restore_state"
down_revision: str | None = "0031_memory_embedding_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("deleted_from_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("agent_memories", recreate="always") as batch:
            batch.drop_column("deleted_from_status")
    else:
        op.drop_column("agent_memories", "deleted_from_status")
