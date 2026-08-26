"""persist the explicitly selected LLM provider

Revision ID: 0010_persist_llm_active_provider
Revises: 0009_llm_provider_credentials
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0010_persist_llm_active_provider"
down_revision: str | None = "0009_llm_provider_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("llm_active_provider", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "llm_active_provider")
