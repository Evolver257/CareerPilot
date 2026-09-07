"""Persist Quick Matching V3 reliability and hard-constraint explanations."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_quick_matching_v3"
down_revision: str | None = "0024_requirement_matching_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_scores",
        sa.Column("score_status", sa.String(30), nullable=False, server_default="SUFFICIENT"),
    )
    op.create_index("ix_job_scores_score_status", "job_scores", ["score_status"])
    op.add_column(
        "job_scores",
        sa.Column("confidence_factors", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "job_scores",
        sa.Column("hard_constraint_ledger", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("job_scores", "hard_constraint_ledger")
    op.drop_column("job_scores", "confidence_factors")
    op.drop_index("ix_job_scores_score_status", table_name="job_scores")
    op.drop_column("job_scores", "score_status")
