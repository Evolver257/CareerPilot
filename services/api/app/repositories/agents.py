from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import AgentEvent, AgentRun, AgentStep


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_runs(self) -> tuple[list[AgentRun], int]:
        query = (
            select(AgentRun)
            .options(selectinload(AgentRun.steps), selectinload(AgentRun.events))
            .order_by(AgentRun.created_at.desc())
        )
        total = int((await self.session.scalar(select(func.count(AgentRun.id)))) or 0)
        runs = list((await self.session.scalars(query)).unique().all())
        return runs, total

    async def get_run(self, run_id: UUID) -> AgentRun | None:
        return await self.session.scalar(
            select(AgentRun)
            .execution_options(populate_existing=True)
            .options(selectinload(AgentRun.steps), selectinload(AgentRun.events))
            .where(AgentRun.id == run_id)
        )

    async def get_status(self, run_id: UUID) -> str | None:
        return await self.session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))

    def add_step(self, step: AgentStep) -> None:
        self.session.add(step)

    def add_event(self, event: AgentEvent) -> None:
        self.session.add(event)

    async def checkpoint(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.commit()
        refreshed = await self.get_run(run.id)
        if refreshed is None:
            raise RuntimeError("Agent run disappeared during persistence")
        return refreshed
