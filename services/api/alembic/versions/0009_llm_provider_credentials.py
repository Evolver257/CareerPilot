"""add encrypted user LLM provider credentials

Revision ID: 0009_llm_provider_credentials
Revises: 0008_decode_boss_salary
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_llm_provider_credentials"
down_revision: str | None = "0008_decode_boss_salary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_key_hint", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_llm_provider_credentials_user_provider"
        ),
    )
    op.create_index(
        "ix_llm_provider_credentials_user_id", "llm_provider_credentials", ["user_id"]
    )
    op.create_index(
        "ix_llm_provider_credentials_provider", "llm_provider_credentials", ["provider"]
    )
    op.create_index(
        "ix_llm_provider_credentials_is_active", "llm_provider_credentials", ["is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_provider_credentials_is_active", table_name="llm_provider_credentials")
    op.drop_index("ix_llm_provider_credentials_provider", table_name="llm_provider_credentials")
    op.drop_index("ix_llm_provider_credentials_user_id", table_name="llm_provider_credentials")
    op.drop_table("llm_provider_credentials")
