"""Add atomic JD requirements and explainable V2 requirement matches."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_requirement_matching_v2"
down_revision: str | None = "0023_qwen3_embedding_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_type", sa.String(40), nullable=False),
        sa.Column("normalized_value", sa.String(300), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_section", sa.String(50), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("is_hard", sa.Boolean(), nullable=False),
        sa.Column("is_critical", sa.Boolean(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("specificity", sa.Float(), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "job_id",
        "requirement_type",
        "normalized_value",
        "is_hard",
        "is_critical",
        "parser_version",
    ):
        op.create_index(f"ix_job_requirements_{column}", "job_requirements", [column])

    op.add_column(
        "job_scores", sa.Column("direction_score", sa.Float(), nullable=False, server_default="0")
    )
    op.add_column(
        "job_scores", sa.Column("score_confidence", sa.Float(), nullable=False, server_default="0")
    )
    op.add_column(
        "job_scores",
        sa.Column("hard_constraint_passed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "requirement_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_score_id", sa.Uuid(), nullable=False),
        sa.Column("job_requirement_id", sa.Uuid(), nullable=True),
        sa.Column("requirement_type", sa.String(40), nullable=False),
        sa.Column("requirement_value", sa.String(300), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("match_method", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("deduction", sa.Float(), nullable=False),
        sa.Column("hard_constraint", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_score_id"], ["job_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_requirement_id"], ["job_requirements.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("job_score_id", "job_requirement_id", "requirement_type", "status"):
        op.create_index(f"ix_requirement_matches_{column}", "requirement_matches", [column])


def downgrade() -> None:
    op.drop_table("requirement_matches")
    op.drop_column("job_scores", "hard_constraint_passed")
    op.drop_column("job_scores", "score_confidence")
    op.drop_column("job_scores", "direction_score")
    op.drop_table("job_requirements")
