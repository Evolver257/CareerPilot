"""Add isolated MCP connections and discovered tool cache."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_mcp_connections"
down_revision: str | None = "0027_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("transport", sa.String(length=30), nullable=False),
        sa.Column("endpoint", sa.String(length=1000), nullable=True),
        sa.Column("command", sa.String(length=500), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("credentials_hint", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("permission_scopes", sa.JSON(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("blocked_tools", sa.JSON(), nullable=False),
        sa.Column("connect_timeout", sa.Float(), nullable=False),
        sa.Column("tool_timeout", sa.Float(), nullable=False),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "namespace", name="uq_mcp_connections_user_namespace"),
    )
    op.create_table(
        "mcp_discovered_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("remote_name", sa.String(length=200), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["mcp_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "remote_name", name="uq_mcp_tools_connection_remote_name"
        ),
    )
    for name, table, columns in [
        ("ix_mcp_connections_user_id", "mcp_connections", ["user_id"]),
        ("ix_mcp_connections_status", "mcp_connections", ["status"]),
        ("ix_mcp_tools_connection_id", "mcp_discovered_tools", ["connection_id"]),
        ("ix_mcp_tools_canonical_name", "mcp_discovered_tools", ["canonical_name"]),
        ("ix_mcp_tools_schema_hash", "mcp_discovered_tools", ["schema_hash"]),
        ("ix_mcp_tools_active", "mcp_discovered_tools", ["active"]),
    ]:
        op.create_index(name, table, columns)


def downgrade() -> None:
    op.drop_table("mcp_discovered_tools")
    op.drop_table("mcp_connections")
