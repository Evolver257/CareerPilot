"""Reconcile plan completion from persisted application outcomes, not browser events."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Application, Campaign


async def reconcile_campaign_completion(
    session: AsyncSession, campaign_id: UUID | None = None,
) -> None:
    await session.flush()
    applications = select(Application.id).where(Application.campaign_id == Campaign.id)
    statement = update(Campaign).where(
        Campaign.status.in_(["RUNNING", "PAUSED", "WAITING_APPROVAL"]),
        exists(applications),
        ~exists(applications.where(Application.status.not_in(["SUBMITTED", "CANCELLED"]))),
    )
    if campaign_id is not None:
        statement = statement.where(Campaign.id == campaign_id)
    # Retryable failures and pending approval are deliberately not terminal.
    await session.execute(statement.values(
        status=case(
            (exists(applications.where(Application.status == "SUBMITTED")), "COMPLETED"),
            else_="CANCELLED",
        ),
        finished_at=datetime.now(UTC),
        status_before_pause=None,
    ).execution_options(synchronize_session=False))
