"""connect campaigns to durable asynchronous ranking runs

Revision ID: 0012_campaign_async_ranking
Revises: 0011_async_ranking_cache
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_campaign_async_ranking"
down_revision: str | None = "0011_async_ranking_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("scoring_mode", sa.String(length=20), nullable=False, server_default="llm"),
    )
    with op.batch_alter_table("ranking_runs") as batch_op:
        batch_op.add_column(sa.Column("campaign_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="1800")
        )
        batch_op.create_foreign_key(
            "fk_ranking_runs_campaign_id_campaigns",
            "campaigns",
            ["campaign_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_ranking_runs_campaign_id", "ranking_runs", ["campaign_id"])
    op.execute(
        "UPDATE campaigns SET status = 'FAILED' "
        "WHERE status = 'RANKING'"
    )


def downgrade() -> None:
    op.drop_index("ix_ranking_runs_campaign_id", table_name="ranking_runs")
    with op.batch_alter_table("ranking_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_ranking_runs_campaign_id_campaigns",
            type_="foreignkey",
        )
        batch_op.drop_column("timeout_seconds")
        batch_op.drop_column("campaign_id")
    op.drop_column("campaigns", "scoring_mode")
