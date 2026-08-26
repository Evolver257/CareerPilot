from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import BrowserTask, BrowserTaskEvent
from app.models.states import BrowserTaskStatus


class BrowserTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tasks(self) -> tuple[list[BrowserTask], int]:
        query = (
            select(BrowserTask)
            .options(selectinload(BrowserTask.events))
            .order_by(BrowserTask.created_at.desc())
        )
        total = int((await self.session.scalar(select(func.count(BrowserTask.id)))) or 0)
        tasks = list((await self.session.scalars(query)).unique().all())
        return tasks, total

    async def get_task(self, task_id: UUID) -> BrowserTask | None:
        return await self.session.scalar(
            select(BrowserTask)
            .execution_options(populate_existing=True)
            .options(selectinload(BrowserTask.events))
            .where(BrowserTask.id == task_id)
        )

    async def get_active_tasks_for_applications(
        self, application_ids: list[UUID]
    ) -> dict[UUID, BrowserTask]:
        if not application_ids:
            return {}
        terminal_statuses = {
            BrowserTaskStatus.COMPLETED.value,
            BrowserTaskStatus.CANCELLED.value,
            BrowserTaskStatus.FAILED.value,
        }
        tasks = list(
            (
                await self.session.scalars(
                    select(BrowserTask)
                    .options(selectinload(BrowserTask.events))
                    .where(
                        BrowserTask.application_id.in_(application_ids),
                        BrowserTask.status.not_in(terminal_statuses),
                    )
                    .order_by(BrowserTask.created_at.desc())
                )
            )
            .unique()
            .all()
        )
        return {task.application_id: task for task in tasks}

    async def add_event(
        self,
        task: BrowserTask,
        event_type: str,
        *,
        payload: dict,
        action_id: str | None = None,
        sequence: int | None = None,
    ) -> None:
        self.session.add(
            BrowserTaskEvent(
                task_id=task.id,
                event_type=event_type,
                action_id=action_id,
                sequence=sequence,
                payload=payload,
            )
        )

    async def checkpoint(self, task: BrowserTask) -> BrowserTask:
        self.session.add(task)
        await self.session.commit()
        refreshed = await self.get_task(task.id)
        if refreshed is None:
            raise RuntimeError("Browser task disappeared during persistence")
        return refreshed
