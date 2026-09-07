from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.provider import LLMProvider
from app.models.entities import BrowserTask
from app.models.states import (
    ApplicationStatus,
    BrowserActionType,
    BrowserTaskEventType,
    BrowserTaskStatus,
)
from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    LoginRequiredError,
    PlatformAdapterError,
    PlatformLimitError,
    RiskControlDetectedError,
    UnknownStateError,
)
from app.platforms.registry import PlatformAdapterRegistry
from app.repositories.browser_tasks import BrowserTaskRepository
from app.repositories.campaigns import CampaignRepository
from app.schemas.browser import (
    BrowserAction,
    BrowserActionResult,
    BrowserExtensionHello,
    BrowserTaskCampaignCreate,
    BrowserTaskCreate,
    BrowserTaskResumeRequest,
)
from app.services.application_state import InvalidStateTransitionError
from app.services.campaigns import CampaignService
from app.services.job_freshness import is_fresh_for_auto_delivery, stale_auto_delivery_reason


class BrowserTaskNotFoundError(ValueError):
    """Raised when a Browser Task does not exist."""


class BrowserTaskActionError(ValueError):
    """Raised when a Browser Task action is invalid."""


@dataclass
class BrowserTaskCampaignResult:
    campaign_id: UUID
    queued_count: int
    created: list[BrowserTask] = field(default_factory=list)
    reused: list[BrowserTask] = field(default_factory=list)
    failures: list[tuple[UUID, str]] = field(default_factory=list)

    @property
    def tasks(self) -> list[BrowserTask]:
        return [*self.created, *self.reused]


class BrowserSocketManager:
    def __init__(self) -> None:
        self.connections: dict[UUID, WebSocket] = {}

    async def connect(self, task_id: UUID, websocket: WebSocket) -> None:
        previous = self.connections.get(task_id)
        if previous is not None:
            await previous.close(code=1012)
        self.connections[task_id] = websocket

    def disconnect(self, task_id: UUID, websocket: WebSocket) -> None:
        if self.connections.get(task_id) is websocket:
            self.connections.pop(task_id, None)

    async def send(self, task_id: UUID, message: dict[str, Any]) -> bool:
        websocket = self.connections.get(task_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
        except Exception:
            self.connections.pop(task_id, None)
            return False
        return True


browser_socket_manager = BrowserSocketManager()


class BrowserTaskService:
    def __init__(self, session: AsyncSession, provider: LLMProvider) -> None:
        self.session = session
        self.repository = BrowserTaskRepository(session)
        self.campaign_repository = CampaignRepository(session)
        self.campaign_service = CampaignService(session, provider)
        self.settings = get_settings()
        self.adapters = PlatformAdapterRegistry(session)

    async def list_tasks(self) -> tuple[list[BrowserTask], int]:
        return await self.repository.list_tasks()

    async def list_campaign_task_groups(self) -> list[list[BrowserTask]]:
        tasks = await self.repository.list_campaign_tasks()
        grouped: dict[UUID, list[BrowserTask]] = {}
        for task in tasks:
            if task.campaign_id is not None:
                grouped.setdefault(task.campaign_id, []).append(task)
        return sorted(
            grouped.values(),
            key=lambda items: max(task.updated_at for task in items),
            reverse=True,
        )

    async def get_campaign_task_group(self, campaign_id: UUID) -> list[BrowserTask]:
        tasks = await self.repository.list_campaign_tasks(campaign_id)
        if not tasks:
            raise BrowserTaskNotFoundError("Campaign Browser Task record not found")
        return tasks

    async def cancel_campaign_tasks(self, campaign_id: UUID) -> list[BrowserTask]:
        tasks = await self.get_campaign_task_group(campaign_id)
        task_ids = [task.id for task in tasks]
        terminal = {
            BrowserTaskStatus.COMPLETED.value,
            BrowserTaskStatus.CANCELLED.value,
        }
        for task in tasks:
            if task.status not in terminal:
                await self.cancel(task.id, notify_extension=False)
        for task_id in task_ids:
            delivered = await browser_socket_manager.send(
                task_id,
                {
                    "type": "TASK_BATCH_CANCELLED",
                    "task_ids": [str(value) for value in task_ids],
                },
            )
            if delivered:
                break
        return await self.get_campaign_task_group(campaign_id)

    async def delete_campaign_task_records(self, campaign_id: UUID) -> None:
        tasks = await self.get_campaign_task_group(campaign_id)
        active = {
            BrowserTaskStatus.PENDING.value,
            BrowserTaskStatus.CONNECTING.value,
            BrowserTaskStatus.RUNNING.value,
            BrowserTaskStatus.WAITING_FOR_USER.value,
        }
        if any(task.status in active for task in tasks):
            raise BrowserTaskActionError(
                "Active Campaign Browser Tasks must be cancelled before deletion"
            )
        await self.repository.delete_campaign_tasks(campaign_id)

    async def get_task(self, task_id: UUID) -> BrowserTask:
        task = await self.repository.get_task(task_id)
        if task is None:
            raise BrowserTaskNotFoundError("Browser Task not found")
        return task

    async def create(self, payload: BrowserTaskCreate) -> BrowserTask:
        application = await self.campaign_repository.get_application(payload.application_id)
        if application is None:
            raise BrowserTaskActionError("Application not found")
        if application.platform != payload.platform:
            raise BrowserTaskActionError("Application platform does not match the task platform")
        if not is_fresh_for_auto_delivery(
            application.job,
            max_age_days=self.settings.auto_delivery_max_job_age_days,
        ):
            raise BrowserTaskActionError(
                stale_auto_delivery_reason(
                    application.job,
                    max_age_days=self.settings.auto_delivery_max_job_age_days,
                )
            )
        try:
            adapter = self.adapters.get(payload.platform)
            prepared = await adapter.prepare_application(
                application_id=application.id, scenario=payload.scenario
            )
        except (PlatformAdapterError, ValueError) as exc:
            raise BrowserTaskActionError(str(exc)) from exc
        task = BrowserTask(
            id=uuid4(),
            user_id=application.user_id,
            application_id=application.id,
            campaign_id=application.campaign_id,
            platform=payload.platform,
            task_type="submit_application",
            scenario=payload.scenario.upper(),
            status=BrowserTaskStatus.PENDING.value,
            payload={
                "actions": [action.model_dump(mode="json") for action in prepared.actions],
                "context": prepared.context,
                "next_action_index": 0,
                "observations": {},
            },
            result={},
            current_action={},
            action_sequence=0,
        )
        actions = list(task.payload["actions"])
        if actions:
            url = actions[0].get("url")
            if isinstance(url, str):
                actions[0]["url"] = url.replace("{task_id}", str(task.id))
            task.payload = {**task.payload, "actions": actions}
        await self.repository.add_event(
            task,
            BrowserTaskEventType.TASK_CREATED.value,
            payload={"platform": payload.platform, "scenario": task.scenario},
        )
        task = await self.repository.checkpoint(task)
        return await self.start(task.id) if payload.auto_start else task

    async def create_for_campaign(
        self, payload: BrowserTaskCampaignCreate
    ) -> BrowserTaskCampaignResult:
        campaign = await self.campaign_repository.get_campaign(payload.campaign_id)
        if campaign is None:
            raise BrowserTaskActionError("Campaign not found")
        queued = [
            application
            for application in campaign.applications
            if application.status == ApplicationStatus.QUEUED.value
            and (payload.platform is None or application.platform == payload.platform)
        ]
        result = BrowserTaskCampaignResult(
            campaign_id=campaign.id,
            queued_count=len(queued),
        )
        eligible = []
        for application in queued:
            if is_fresh_for_auto_delivery(
                application.job,
                max_age_days=self.settings.auto_delivery_max_job_age_days,
            ):
                eligible.append(application)
            else:
                result.failures.append(
                    (
                        application.id,
                        stale_auto_delivery_reason(
                            application.job,
                            max_age_days=self.settings.auto_delivery_max_job_age_days,
                        ),
                    )
                )
        active_tasks = await self.repository.get_active_tasks_for_applications(
            [application.id for application in eligible]
        )
        for application in eligible:
            existing = active_tasks.get(application.id)
            if existing is not None:
                result.reused.append(existing)
                continue
            try:
                task = await self.create(
                    BrowserTaskCreate(
                        application_id=application.id,
                        platform=application.platform,
                        scenario=payload.scenario,
                        auto_start=payload.auto_start,
                    )
                )
                result.created.append(task)
            except BrowserTaskActionError as exc:
                result.failures.append((application.id, str(exc)))
        return result

    async def start(self, task_id: UUID) -> BrowserTask:
        task = await self.get_task(task_id)
        if task.status not in {
            BrowserTaskStatus.PENDING.value,
            BrowserTaskStatus.CONNECTING.value,
        }:
            raise BrowserTaskActionError(f"Browser Task cannot start from {task.status}")
        application = await self.campaign_repository.get_application(task.application_id)
        if application is None:
            raise BrowserTaskActionError("Application no longer exists")
        if not is_fresh_for_auto_delivery(
            application.job,
            max_age_days=self.settings.auto_delivery_max_job_age_days,
        ):
            raise BrowserTaskActionError(
                stale_auto_delivery_reason(
                    application.job,
                    max_age_days=self.settings.auto_delivery_max_job_age_days,
                )
            )
        if application.status == ApplicationStatus.QUEUED.value:
            try:
                await self.campaign_service.transition_application(
                    application.id, action="execute", reason=None
                )
            except InvalidStateTransitionError as exc:
                raise BrowserTaskActionError(str(exc)) from exc
        task = await self.get_task(task.id)
        task.status = BrowserTaskStatus.CONNECTING.value
        task.started_at = task.started_at or datetime.now(UTC)
        task = await self._checkpoint(task)
        if task.id in browser_socket_manager.connections:
            return await self._begin_extension_session(task)
        return task

    async def connect_extension(
        self, task_id: UUID, websocket: WebSocket, hello: BrowserExtensionHello | None
    ) -> BrowserTask:
        task = await self.get_task(task_id)
        if task.status in {
            BrowserTaskStatus.COMPLETED.value,
            BrowserTaskStatus.CANCELLED.value,
        }:
            raise BrowserTaskActionError(f"Browser Task is already {task.status}")
        await browser_socket_manager.connect(task.id, websocket)
        await self.repository.add_event(
            task,
            BrowserTaskEventType.EXTENSION_CONNECTED.value,
            payload=hello.model_dump(mode="json") if hello else {},
        )
        task = await self._checkpoint(task)
        if task.status == BrowserTaskStatus.PENDING.value:
            return await self.start(task.id)
        return await self._begin_extension_session(task)

    async def handle_action_result(self, task_id: UUID, result: BrowserActionResult) -> BrowserTask:
        task = await self.get_task(task_id)
        if task.status != BrowserTaskStatus.RUNNING.value:
            raise BrowserTaskActionError(f"Browser Task is not running: {task.status}")
        action = self._current_action(task)
        if action.id != result.action_id:
            raise BrowserTaskActionError("Action result does not match the current action")
        payload = dict(task.payload)
        observations = dict(payload.get("observations", {}))
        observations[action.id] = result.model_dump(mode="json")
        payload["observations"] = observations
        # Keep a separate top-level object: application transitions may commit
        # this snapshot before next_action_index/submission are updated below.
        task.payload = dict(payload)
        await self.repository.add_event(
            task,
            BrowserTaskEventType.ACTION_RESULT.value,
            action_id=action.id,
            sequence=task.action_sequence,
            payload=result.model_dump(mode="json"),
        )
        if not result.success:
            if self._is_manual_application_required(result):
                return await self._complete_manual_required(
                    task,
                    result,
                    observations,
                )
            if task.platform in {"boss", "zhaopin"} and action.action in {
                BrowserActionType.CLICK,
                BrowserActionType.CHECK_STATE,
            }:
                error_type = {
                    "CAPTCHA": CaptchaRequiredError,
                    "LOGIN_REQUIRED": LoginRequiredError,
                    "RISK_CONTROL": RiskControlDetectedError,
                    "PLATFORM_LIMIT": PlatformLimitError,
                    "UNKNOWN_STATE": UnknownStateError,
                }.get(result.page_state, DomChangedError)
                error = error_type(result.error or "招聘页面未就绪或投递按钮无法操作，请人工检查")
                await self._mark_application_failure(task.application_id, error)
                return await self._wait_for_user(task, str(error))
            return await self._fail_task(task, result.error or "Browser action failed")
        if action.action == BrowserActionType.CLICK:
            try:
                submitted = await self.adapters.get(task.platform).submit_application(
                    application_id=task.application_id,
                    scenario=task.scenario,
                    observations=observations,
                )
                await self.campaign_service.transition_application(
                    task.application_id, action="submit", reason=None
                )
                payload["submission"] = {
                    "external_id": submitted.external_id,
                    "status": submitted.status,
                    "message": submitted.message,
                }
            except (
                CaptchaRequiredError,
                LoginRequiredError,
                PlatformLimitError,
                DomChangedError,
                RiskControlDetectedError,
                UnknownStateError,
            ) as exc:
                await self._mark_application_failure(task.application_id, exc)
                return await self._wait_for_user(task, str(exc))
            except (InvalidStateTransitionError, RuntimeError, PlatformAdapterError) as exc:
                await self._mark_application_failure(task.application_id, exc)
                return await self._fail_task(task, str(exc))
        payload["next_action_index"] = int(payload.get("next_action_index", 0)) + 1
        task.payload = payload
        task = await self._checkpoint(task)
        if action.action == BrowserActionType.EXTRACT:
            task.status = BrowserTaskStatus.COMPLETED.value
            task.result = {
                "status": "SUBMITTED",
                "submission": payload.get("submission", {}),
                "observations": observations,
            }
            task.finished_at = datetime.now(UTC)
            await self.repository.add_event(
                task,
                BrowserTaskEventType.TASK_COMPLETED.value,
                payload=task.result,
            )
            task = await self._checkpoint(task)
            await browser_socket_manager.send(
                task.id,
                {
                    "type": "TASK_COMPLETED",
                    "task_id": str(task.id),
                    "status": BrowserTaskStatus.COMPLETED.value,
                },
            )
            return task
        return await self._send_next_action(task)

    @staticmethod
    def _is_manual_application_required(result: BrowserActionResult) -> bool:
        return (
            str(result.data.get("application_status", "")).upper()
            == ApplicationStatus.MANUAL_REQUIRED.value
        )

    async def _complete_manual_required(
        self,
        task: BrowserTask,
        result: BrowserActionResult,
        observations: dict[str, Any],
    ) -> BrowserTask:
        reason = result.error or "该岗位仅支持立即网申，请在 BOSS 原页面手动投递"
        try:
            await self.campaign_service.transition_application(
                task.application_id,
                action="manual_required",
                reason=reason,
            )
        except InvalidStateTransitionError as exc:
            return await self._fail_task(task, str(exc))

        task.payload = {
            **task.payload,
            "observations": observations,
            "next_action_index": int(task.payload.get("next_action_index", 0)) + 1,
            "manual_required": {"reason": reason, "platform": task.platform},
        }
        task.status = BrowserTaskStatus.COMPLETED.value
        task.result = {
            "status": ApplicationStatus.MANUAL_REQUIRED.value,
            "application_status": ApplicationStatus.MANUAL_REQUIRED.value,
            "reason": reason,
            "observations": observations,
        }
        task.finished_at = datetime.now(UTC)
        await self.repository.add_event(
            task,
            BrowserTaskEventType.TASK_COMPLETED.value,
            payload=task.result,
        )
        task = await self._checkpoint(task)
        await browser_socket_manager.send(
            task.id,
            {
                "type": "TASK_COMPLETED",
                "task_id": str(task.id),
                "status": BrowserTaskStatus.COMPLETED.value,
                "application_status": ApplicationStatus.MANUAL_REQUIRED.value,
            },
        )
        return task

    async def resume(self, task_id: UUID, payload: BrowserTaskResumeRequest) -> BrowserTask:
        task = await self.get_task(task_id)
        if task.status != BrowserTaskStatus.WAITING_FOR_USER.value:
            raise BrowserTaskActionError(f"Browser Task cannot resume from {task.status}")
        if payload.decision.casefold() == "cancel":
            return await self.cancel(task.id)
        try:
            recovered = await self.campaign_service.transition_application(
                task.application_id, action="retry", reason=payload.note
            )
            if recovered.status == ApplicationStatus.QUEUED.value:
                await self.campaign_service.transition_application(
                    task.application_id, action="execute", reason=None
                )
        except InvalidStateTransitionError as exc:
            raise BrowserTaskActionError(str(exc)) from exc
        task.scenario = "SUCCESS"
        task.status = BrowserTaskStatus.RUNNING.value
        task.failure_reason = None
        task.result = {**task.result, "user_action": payload.note or "resolved"}
        task = await self._checkpoint(task)
        return await self._send_next_action(task)

    async def simulate_extension(self, task_id: UUID) -> BrowserTask:
        """Run the same action/result contract without a browser for CI demos."""
        task = await self.get_task(task_id)
        if task.status == BrowserTaskStatus.PENDING.value:
            task = await self.start(task.id)
        if task.status == BrowserTaskStatus.CONNECTING.value:
            task.status = BrowserTaskStatus.RUNNING.value
            task = await self._send_next_action(await self._checkpoint(task))
        for _ in range(10):
            task = await self.get_task(task.id)
            if task.status != BrowserTaskStatus.RUNNING.value:
                return task
            action = self._current_action(task)
            mock_data: dict[str, Any] = {"mock_extension": True, "page_state": action.action}
            if task.platform == "boss":
                context = task.payload.get("context", {})
                source_url = context.get("source_url") if isinstance(context, dict) else None
                mock_data.update(
                    {
                        "page_url": source_url,
                        "text": "职位详情 立即沟通",
                        "platform": "boss",
                    }
                )
                if action.action == BrowserActionType.CLICK:
                    mock_data.update(
                        {
                            "boss_action": "immediate_communication",
                            "communication_status": "started",
                            "clicked_text": "立即沟通",
                        }
                    )
            manual_required = (
                task.scenario == "MANUAL_REQUIRED"
                and action.action == BrowserActionType.CLICK
            )
            if manual_required:
                mock_data.update(
                    {
                        "application_status": ApplicationStatus.MANUAL_REQUIRED.value,
                        "boss_action": "manual_apply_required",
                    }
                )
            task = await self.handle_action_result(
                task.id,
                BrowserActionResult(
                    action_id=action.id,
                    success=not manual_required,
                    data=mock_data,
                    page_state="READY" if manual_required else None,
                    error=(
                        "该岗位仅支持‘立即网申’，已跳过，请手动投递"
                        if manual_required
                        else None
                    ),
                ),
            )
        raise BrowserTaskActionError("Mock Extension exceeded the action limit")

    async def cancel(self, task_id: UUID, *, notify_extension: bool = True) -> BrowserTask:
        task = await self.get_task(task_id)
        if task.status in {
            BrowserTaskStatus.COMPLETED.value,
            BrowserTaskStatus.CANCELLED.value,
        }:
            raise BrowserTaskActionError(f"Browser Task cannot cancel from {task.status}")
        application = await self.campaign_repository.get_application(task.application_id)
        if application and application.status not in {
            ApplicationStatus.SUBMITTED.value,
            ApplicationStatus.CANCELLED.value,
        }:
            try:
                await self.campaign_service.transition_application(
                    task.application_id, action="cancel", reason="Browser Task cancelled"
                )
            except InvalidStateTransitionError as exc:
                raise BrowserTaskActionError(str(exc)) from exc
        task.status = BrowserTaskStatus.CANCELLED.value
        task.finished_at = datetime.now(UTC)
        await self.repository.add_event(task, BrowserTaskEventType.TASK_CANCELLED.value, payload={})
        task = await self._checkpoint(task)
        if notify_extension:
            await browser_socket_manager.send(
                task.id,
                {
                    "type": "TASK_CANCELLED",
                    "task_id": str(task.id),
                    "status": BrowserTaskStatus.CANCELLED.value,
                },
            )
        return task

    async def _begin_extension_session(self, task: BrowserTask) -> BrowserTask:
        if task.status == BrowserTaskStatus.CONNECTING.value:
            task.status = BrowserTaskStatus.RUNNING.value
            task = await self._checkpoint(task)
        return await self._send_next_action(task)

    async def _send_next_action(self, task: BrowserTask) -> BrowserTask:
        actions = [BrowserAction.model_validate(item) for item in task.payload.get("actions", [])]
        index = int(task.payload.get("next_action_index", 0))
        if index >= len(actions):
            return task
        action = actions[index]
        task.action_sequence += 1
        task.current_action = action.model_dump(mode="json")
        await self.repository.add_event(
            task,
            BrowserTaskEventType.ACTION_SENT.value,
            action_id=action.id,
            sequence=task.action_sequence,
            payload=task.current_action,
        )
        task = await self._checkpoint(task)
        await browser_socket_manager.send(
            task.id,
            {
                "type": "ACTION",
                "task_id": str(task.id),
                "sequence": task.action_sequence,
                "action": task.current_action,
            },
        )
        return task

    async def _wait_for_user(self, task: BrowserTask, reason: str) -> BrowserTask:
        task.status = BrowserTaskStatus.WAITING_FOR_USER.value
        task.failure_reason = reason
        task.current_action = BrowserAction(
            action=BrowserActionType.REQUEST_USER_ACTION,
            metadata={"reason": reason, "task_id": str(task.id)},
        ).model_dump(mode="json")
        await self.repository.add_event(
            task,
            BrowserTaskEventType.USER_ACTION_REQUIRED.value,
            payload=task.current_action,
        )
        task = await self._checkpoint(task)
        await browser_socket_manager.send(
            task.id,
            {"type": "REQUEST_USER_ACTION", "task_id": str(task.id), "action": task.current_action},
        )
        return task

    async def _fail_task(self, task: BrowserTask, reason: str) -> BrowserTask:
        task_id = task.id
        await self.session.rollback()
        task = await self.get_task(task_id)
        task.status = BrowserTaskStatus.FAILED.value
        task.failure_reason = reason
        task.finished_at = datetime.now(UTC)
        await self.repository.add_event(
            task, BrowserTaskEventType.TASK_FAILED.value, payload={"reason": reason}
        )
        task = await self._checkpoint(task)
        await browser_socket_manager.send(
            task.id,
            {
                "type": "TASK_FAILED",
                "task_id": str(task.id),
                "status": BrowserTaskStatus.FAILED.value,
                "error": reason,
            },
        )
        return task

    async def _mark_application_failure(self, application_id: UUID, error: Exception) -> None:
        action = {
            CaptchaRequiredError: "captcha_required",
            LoginRequiredError: "login_required",
            PlatformLimitError: "platform_limit",
            DomChangedError: "dom_changed",
            RiskControlDetectedError: "risk_control",
            UnknownStateError: "unknown_state",
        }.get(type(error), "fail")
        try:
            await self.campaign_service.transition_application(
                application_id, action=action, reason=str(error)
            )
        except InvalidStateTransitionError:
            # The Browser Task still records the adapter failure even if the
            # application was changed by a concurrent user action.
            await self.session.rollback()

    async def _checkpoint(self, task: BrowserTask) -> BrowserTask:
        return await self.repository.checkpoint(task)

    def _current_action(self, task: BrowserTask) -> BrowserAction:
        if not task.current_action:
            raise BrowserTaskActionError("Browser Task has no current action")
        return BrowserAction.model_validate(task.current_action)
