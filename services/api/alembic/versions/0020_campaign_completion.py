"""Repair terminal plans without removing applications or execution history."""

from alembic import op

revision = "0020_campaign_completion"
down_revision = "0019_background_work"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        UPDATE campaigns SET
            status = CASE WHEN EXISTS (
                SELECT 1 FROM applications a
                WHERE a.campaign_id = campaigns.id AND a.status = 'SUBMITTED'
            ) THEN 'COMPLETED' ELSE 'CANCELLED' END,
            finished_at = CURRENT_TIMESTAMP, status_before_pause = NULL
        WHERE status IN ('RUNNING', 'PAUSED', 'WAITING_APPROVAL')
          AND EXISTS (SELECT 1 FROM applications a WHERE a.campaign_id = campaigns.id)
          AND NOT EXISTS (
            SELECT 1 FROM applications a WHERE a.campaign_id = campaigns.id
            AND a.status NOT IN ('SUBMITTED', 'CANCELLED')
          )
    """)


def downgrade():
    # Actual completed/cancelled outcomes must not be reverted to running.
    pass
