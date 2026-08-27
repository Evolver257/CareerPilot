"""add versioned job knowledge base and resumable index runs

Revision ID: 0014_job_knowledge_base
Revises: 0013_market_insight_reports
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.embedding import EmbeddingType

revision: str = "0014_job_knowledge_base"
down_revision: str | None = "0013_market_insight_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "job_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("raw_title", sa.String(length=300), nullable=False),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("source_platform", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "version_number", name="uq_job_versions_job_version"),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_job_versions_job_content_hash"),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"])
    op.create_index("ix_job_versions_is_current", "job_versions", ["is_current"])

    op.create_table(
        "job_knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("role_family", sa.String(length=200), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=False),
        sa.Column("normalized_city", sa.String(length=300), nullable=False),
        sa.Column("normalized_education", sa.String(length=500), nullable=False),
        sa.Column("normalized_experience", sa.String(length=500), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_unit", sa.String(length=40), nullable=False),
        sa.Column("employment_type", sa.String(length=100), nullable=False),
        sa.Column("current_embedding_signature", sa.String(length=300), nullable=False),
        sa.Column("knowledge_version", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_version_id", name="uq_job_knowledge_documents_version"),
    )
    op.create_index("ix_job_knowledge_documents_job_id", "job_knowledge_documents", ["job_id"])
    op.create_index(
        "ix_job_knowledge_documents_job_version_id",
        "job_knowledge_documents",
        ["job_version_id"],
    )
    op.create_index("ix_job_knowledge_documents_active", "job_knowledge_documents", ["active"])

    op.create_table(
        "job_knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("section_type", sa.String(length=60), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", EmbeddingType(384), nullable=True),
        sa.Column("embedding_provider", sa.String(length=80), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_signature", sa.String(length=300), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["job_knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "section_type",
            "content_hash",
            name="uq_job_knowledge_chunks_document_section_hash",
        ),
    )
    op.create_index("ix_job_knowledge_chunks_document_id", "job_knowledge_chunks", ["document_id"])
    op.create_index("ix_job_knowledge_chunks_job_id", "job_knowledge_chunks", ["job_id"])
    op.create_index(
        "ix_job_knowledge_chunks_section_type", "job_knowledge_chunks", ["section_type"]
    )
    op.create_index(
        "ix_job_knowledge_chunks_content_hash", "job_knowledge_chunks", ["content_hash"]
    )
    op.create_index(
        "ix_job_knowledge_chunks_embedding_signature",
        "job_knowledge_chunks",
        ["embedding_signature"],
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_job_knowledge_chunks_embedding_hnsw "
            "ON job_knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
        )

    op.create_table(
        "skill_taxonomy",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["skill_taxonomy.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name"),
    )
    op.create_index("ix_skill_taxonomy_canonical_name", "skill_taxonomy", ["canonical_name"])
    op.create_index("ix_skill_taxonomy_category", "skill_taxonomy", ["category"])
    op.create_index("ix_skill_taxonomy_parent_id", "skill_taxonomy", ["parent_id"])
    op.create_index("ix_skill_taxonomy_active", "skill_taxonomy", ["active"])

    op.create_table(
        "skill_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
        sa.Column("normalized_alias", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill_taxonomy.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_alias"),
    )
    op.create_index("ix_skill_aliases_skill_id", "skill_aliases", ["skill_id"])
    op.create_index("ix_skill_aliases_normalized_alias", "skill_aliases", ["normalized_alias"])

    op.create_table(
        "job_skill_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_type", sa.String(length=30), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill_taxonomy.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "skill_id", name="uq_job_skill_facts_job_skill"),
    )
    op.create_index("ix_job_skill_facts_job_id", "job_skill_facts", ["job_id"])
    op.create_index("ix_job_skill_facts_skill_id", "job_skill_facts", ["skill_id"])
    op.create_index("ix_job_skill_facts_requirement_type", "job_skill_facts", ["requirement_type"])

    op.create_table(
        "knowledge_index_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total_jobs", sa.Integer(), nullable=False),
        sa.Column("processed_jobs", sa.Integer(), nullable=False),
        sa.Column("succeeded_jobs", sa.Integer(), nullable=False),
        sa.Column("skipped_jobs", sa.Integer(), nullable=False),
        sa.Column("failed_jobs", sa.Integer(), nullable=False),
        sa.Column("current_job_id", sa.Uuid(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["current_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_index_runs_mode", "knowledge_index_runs", ["mode"])
    op.create_index("ix_knowledge_index_runs_status", "knowledge_index_runs", ["status"])
    op.create_index(
        "ix_knowledge_index_runs_current_job_id", "knowledge_index_runs", ["current_job_id"]
    )

    op.create_table(
        "knowledge_index_run_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("reused_embedding_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_index_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "job_id", name="uq_knowledge_index_items_run_job"),
    )
    op.create_index("ix_knowledge_index_run_items_run_id", "knowledge_index_run_items", ["run_id"])
    op.create_index("ix_knowledge_index_run_items_job_id", "knowledge_index_run_items", ["job_id"])
    op.create_index("ix_knowledge_index_run_items_status", "knowledge_index_run_items", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_job_knowledge_chunks_embedding_hnsw")

    op.drop_index("ix_knowledge_index_run_items_status", table_name="knowledge_index_run_items")
    op.drop_index("ix_knowledge_index_run_items_job_id", table_name="knowledge_index_run_items")
    op.drop_index("ix_knowledge_index_run_items_run_id", table_name="knowledge_index_run_items")
    op.drop_table("knowledge_index_run_items")

    op.drop_index("ix_knowledge_index_runs_current_job_id", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_status", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_mode", table_name="knowledge_index_runs")
    op.drop_table("knowledge_index_runs")

    op.drop_index("ix_job_skill_facts_requirement_type", table_name="job_skill_facts")
    op.drop_index("ix_job_skill_facts_skill_id", table_name="job_skill_facts")
    op.drop_index("ix_job_skill_facts_job_id", table_name="job_skill_facts")
    op.drop_table("job_skill_facts")

    op.drop_index("ix_skill_aliases_normalized_alias", table_name="skill_aliases")
    op.drop_index("ix_skill_aliases_skill_id", table_name="skill_aliases")
    op.drop_table("skill_aliases")

    op.drop_index("ix_skill_taxonomy_active", table_name="skill_taxonomy")
    op.drop_index("ix_skill_taxonomy_parent_id", table_name="skill_taxonomy")
    op.drop_index("ix_skill_taxonomy_category", table_name="skill_taxonomy")
    op.drop_index("ix_skill_taxonomy_canonical_name", table_name="skill_taxonomy")
    op.drop_table("skill_taxonomy")

    op.drop_index(
        "ix_job_knowledge_chunks_embedding_signature", table_name="job_knowledge_chunks"
    )
    op.drop_index("ix_job_knowledge_chunks_content_hash", table_name="job_knowledge_chunks")
    op.drop_index("ix_job_knowledge_chunks_section_type", table_name="job_knowledge_chunks")
    op.drop_index("ix_job_knowledge_chunks_job_id", table_name="job_knowledge_chunks")
    op.drop_index("ix_job_knowledge_chunks_document_id", table_name="job_knowledge_chunks")
    op.drop_table("job_knowledge_chunks")

    op.drop_index("ix_job_knowledge_documents_active", table_name="job_knowledge_documents")
    op.drop_index(
        "ix_job_knowledge_documents_job_version_id", table_name="job_knowledge_documents"
    )
    op.drop_index("ix_job_knowledge_documents_job_id", table_name="job_knowledge_documents")
    op.drop_table("job_knowledge_documents")

    op.drop_index("ix_job_versions_is_current", table_name="job_versions")
    op.drop_index("ix_job_versions_job_id", table_name="job_versions")
    op.drop_table("job_versions")
