"""Add structured fields and lifecycle metadata to CareerPilot memory.

The columns are deliberately nullable during the migration so existing V1 rows
can be upgraded without losing data.  New writes populate the V2 defaults in
the ORM/service layer, while the backfill below makes legacy rows readable by
both V1 and V2 clients.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_agent_memory_v2"
down_revision: str | None = "0029_evaluation_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_columns(table: str, columns: list[sa.Column]) -> None:
    for column in columns:
        op.add_column(table, column)


def upgrade() -> None:
    _add_columns(
        "agent_memory_settings",
        [
            sa.Column(
                "allow_session_summaries", sa.Boolean(), nullable=True, server_default=sa.false()
            ),
            sa.Column(
                "allow_unconfirmed_context", sa.Boolean(), nullable=True, server_default=sa.false()
            ),
            sa.Column("memory_token_budget", sa.Integer(), nullable=True, server_default="700"),
            sa.Column(
                "extraction_confidence_threshold",
                sa.Float(),
                nullable=True,
                server_default="0.75",
            ),
        ],
    )
    _add_columns(
        "agent_memories",
        [
            sa.Column("memory_key", sa.String(length=200), nullable=True),
            sa.Column("structured_value", sa.JSON(), nullable=True),
            sa.Column("scope", sa.String(length=120), nullable=True),
            sa.Column("memory_class", sa.String(length=20), nullable=True),
            sa.Column("stability", sa.String(length=20), nullable=True),
            sa.Column("importance", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True, server_default="ACTIVE"),
            sa.Column("source_quote", sa.Text(), nullable=True),
            sa.Column("extraction_method", sa.String(length=20), nullable=True),
            sa.Column("extraction_version", sa.String(length=50), nullable=True),
            sa.Column("supersedes_id", sa.Uuid(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pinned", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("use_count", sa.Integer(), nullable=True, server_default="0"),
        ],
    )
    _add_columns(
        "memory_candidates",
        [
            sa.Column("memory_key", sa.String(length=200), nullable=True),
            sa.Column("structured_value", sa.JSON(), nullable=True),
            sa.Column("scope", sa.String(length=120), nullable=True),
            sa.Column("memory_class", sa.String(length=20), nullable=True),
            sa.Column("stability", sa.String(length=20), nullable=True),
            sa.Column("importance", sa.Float(), nullable=True),
            sa.Column("source_quote", sa.Text(), nullable=True),
            sa.Column("extraction_method", sa.String(length=20), nullable=True),
            sa.Column("extraction_version", sa.String(length=50), nullable=True),
            sa.Column(
                "requires_confirmation", sa.Boolean(), nullable=True, server_default=sa.true()
            ),
            sa.Column("conflict_type", sa.String(length=20), nullable=True),
        ],
    )

    # Keep legacy data intact and provide deterministic V2 defaults.  The
    # statements are portable across PostgreSQL and SQLite test databases.
    op.execute(
        sa.text(
            "UPDATE agent_memory_settings SET "
            "allow_session_summaries = COALESCE(allow_session_summaries, FALSE), "
            "allow_unconfirmed_context = COALESCE(allow_unconfirmed_context, FALSE), "
            "memory_token_budget = COALESCE(memory_token_budget, 700), "
            "extraction_confidence_threshold = COALESCE(extraction_confidence_threshold, 0.75)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE agent_memories SET memory_key = COALESCE(memory_key, CASE memory_type "
            "WHEN 'CAREER_GOAL' THEN 'career.target_role' "
            "WHEN 'JOB_PREFERENCE' THEN 'preference.general' "
            "WHEN 'SKILL_BACKGROUND' THEN 'skill.general' "
            "WHEN 'LEARNING_PROGRESS' THEN 'learning.progress' "
            "WHEN 'CONVERSATION_SUMMARY' THEN 'conversation.summary' "
            "ELSE lower(memory_type) END), "
            "structured_value = COALESCE(structured_value, '{}'), "
            "memory_class = COALESCE(memory_class, 'SEMANTIC'), "
            "stability = COALESCE(stability, 'STABLE'), "
            "importance = COALESCE(importance, 0.5), "
            "status = COALESCE(status, 'ACTIVE'), "
            "source_quote = COALESCE(source_quote, content), "
            "extraction_method = COALESCE(extraction_method, 'USER'), "
            "extraction_version = COALESCE(extraction_version, 'v1'), "
            "pinned = COALESCE(pinned, FALSE), use_count = COALESCE(use_count, 0)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE memory_candidates SET memory_key = COALESCE(memory_key, CASE memory_type "
            "WHEN 'CAREER_GOAL' THEN 'career.target_role' "
            "WHEN 'JOB_PREFERENCE' THEN 'preference.general' "
            "WHEN 'SKILL_BACKGROUND' THEN 'skill.general' "
            "WHEN 'LEARNING_PROGRESS' THEN 'learning.progress' "
            "WHEN 'CONVERSATION_SUMMARY' THEN 'conversation.summary' "
            "ELSE lower(memory_type) END), "
            "structured_value = COALESCE(structured_value, '{}'), "
            "memory_class = COALESCE(memory_class, 'SEMANTIC'), "
            "stability = COALESCE(stability, 'STABLE'), "
            "importance = COALESCE(importance, 0.5), "
            "source_quote = COALESCE(source_quote, content), "
            "extraction_method = COALESCE(extraction_method, 'RULE'), "
            "extraction_version = COALESCE(extraction_version, 'v1'), "
            "requires_confirmation = COALESCE(requires_confirmation, TRUE)"
        )
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("agent_memories", recreate="always") as batch:
            batch.create_foreign_key(
                "fk_agent_memories_supersedes_id",
                "agent_memories",
                ["supersedes_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            "fk_agent_memories_supersedes_id",
            "agent_memories",
            "agent_memories",
            ["supersedes_id"],
            ["id"],
            ondelete="SET NULL",
        )
    for name, table, columns in (
        ("ix_agent_memories_user_status", "agent_memories", ["user_id", "status"]),
        ("ix_agent_memories_user_memory_key", "agent_memories", ["user_id", "memory_key"]),
        ("ix_agent_memories_user_type", "agent_memories", ["user_id", "memory_type"]),
        ("ix_agent_memories_user_valid_until", "agent_memories", ["user_id", "valid_until"]),
        ("ix_agent_memories_embedding_signature", "agent_memories", ["embedding_signature"]),
        ("ix_memory_candidates_user_memory_key", "memory_candidates", ["user_id", "memory_key"]),
    ):
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table in (
        ("ix_memory_candidates_user_memory_key", "memory_candidates"),
        ("ix_agent_memories_embedding_signature", "agent_memories"),
        ("ix_agent_memories_user_valid_until", "agent_memories"),
        ("ix_agent_memories_user_type", "agent_memories"),
        ("ix_agent_memories_user_memory_key", "agent_memories"),
        ("ix_agent_memories_user_status", "agent_memories"),
    ):
        op.drop_index(name, table_name=table)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("agent_memories", recreate="always") as batch:
            batch.drop_constraint("fk_agent_memories_supersedes_id", type_="foreignkey")
    else:
        op.drop_constraint(
            "fk_agent_memories_supersedes_id", "agent_memories", type_="foreignkey"
        )
    for table, names in (
        (
            "memory_candidates",
            [
                "memory_key",
                "structured_value",
                "scope",
                "memory_class",
                "stability",
                "importance",
                "source_quote",
                "extraction_method",
                "extraction_version",
                "requires_confirmation",
                "conflict_type",
            ],
        ),
        (
            "agent_memories",
            [
                "memory_key",
                "structured_value",
                "scope",
                "memory_class",
                "stability",
                "importance",
                "status",
                "source_quote",
                "extraction_method",
                "extraction_version",
                "supersedes_id",
                "last_verified_at",
                "pinned",
                "use_count",
            ],
        ),
        (
            "agent_memory_settings",
            [
                "allow_session_summaries",
                "allow_unconfirmed_context",
                "memory_token_budget",
                "extraction_confidence_threshold",
            ],
        ),
    ):
        for name in names:
            op.drop_column(table, name)
