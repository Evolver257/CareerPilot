"""Add a durable not-before time used to coalesce incremental indexing bursts."""

import sqlalchemy as sa

from alembic import op

revision = "0021_background_work_schedule"
down_revision = "0020_campaign_completion"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "background_work",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_background_work_available_at", "background_work", ["available_at"])


def downgrade():
    op.drop_index("ix_background_work_available_at", table_name="background_work")
    op.drop_column("background_work", "available_at")
