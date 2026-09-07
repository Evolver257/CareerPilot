"""Durable independent worker queue; jobs and dispatch records commit together."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "0019_background_work"
down_revision = "0018_platform_metadata"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "background_work",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "run_id", name="uq_work_kind_run"),
    )
    op.create_index("ix_background_work_status", "background_work", ["status"])
    # Preserve work queued before the API-to-worker migration. Untouched manual
    # knowledge runs (PENDING) remain manual; interrupted RUNNING runs resume.
    connection = op.get_bind()
    queue = sa.table(
        "background_work",
        *[
            sa.column(name, type_)
            for name, type_ in [
                ("id", sa.Uuid()),
                ("kind", sa.String()),
                ("run_id", sa.Uuid()),
                ("status", sa.String()),
                ("attempts", sa.Integer()),
                ("generation", sa.Integer()),
                ("created_at", sa.DateTime(timezone=True)),
                ("updated_at", sa.DateTime(timezone=True)),
            ]
        ],
    )
    now = datetime.now(UTC)
    for kind, table_name, states in [
        ("ranking", "ranking_runs", ["PENDING", "RUNNING"]),
        ("knowledge", "knowledge_index_runs", ["RUNNING"]),
    ]:
        runs = sa.table(table_name, sa.column("id", sa.Uuid()), sa.column("status", sa.String()))
        for run_id in connection.scalars(sa.select(runs.c.id).where(runs.c.status.in_(states))):
            connection.execute(
                queue.insert().values(
                    id=uuid4(),
                    kind=kind,
                    run_id=run_id,
                    status="PENDING",
                    attempts=0,
                    generation=0,
                    created_at=now,
                    updated_at=now,
                )
            )


def downgrade():
    op.drop_table("background_work")
