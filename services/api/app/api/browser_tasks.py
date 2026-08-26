import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_browser_task_service, get_llm_provider
from app.core.database import get_db
from app.llm.provider import LLMProvider
from app.models.entities import BrowserTask, BrowserTaskEvent
from app.models.states import BrowserTaskStatus
from app.schemas.browser import (
    BrowserActionResult,
    BrowserExtensionHello,
    BrowserTaskCampaignCreate,
    BrowserTaskCampaignFailure,
    BrowserTaskCampaignResponse,
    BrowserTaskCreate,
    BrowserTaskEventRead,
    BrowserTaskListResponse,
    BrowserTaskRead,
    BrowserTaskResumeRequest,
    PlatformAdapterRead,
)
from app.services.browser_tasks import (
    BrowserTaskActionError,
    BrowserTaskNotFoundError,
    BrowserTaskService,
    browser_socket_manager,
)

router = APIRouter(prefix="/api/browser-tasks", tags=["browser-tasks"])


def _event_read(event: BrowserTaskEvent) -> BrowserTaskEventRead:
    return BrowserTaskEventRead(
        id=event.id,
        task_id=event.task_id,
        event_type=event.event_type,
        action_id=event.action_id,
        sequence=event.sequence,
        payload=event.payload,
        created_at=event.created_at,
    )


def _task_read(task: BrowserTask) -> BrowserTaskRead:
    return BrowserTaskRead(
        id=task.id,
        user_id=task.user_id,
        application_id=task.application_id,
        campaign_id=task.campaign_id,
        platform=task.platform,
        task_type=task.task_type,
        scenario=task.scenario,
        status=task.status,
        payload=task.payload,
        result=task.result,
        current_action=task.current_action,
        failure_reason=task.failure_reason,
        action_sequence=task.action_sequence,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        events=[
            _event_read(event)
            for event in sorted(task.events, key=lambda item: item.created_at)
        ],
    )


@router.get("", response_model=BrowserTaskListResponse)
async def list_browser_tasks(
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskListResponse:
    tasks, total = await service.list_tasks()
    return BrowserTaskListResponse(items=[_task_read(task) for task in tasks], total=total)


@router.post("", response_model=BrowserTaskRead, status_code=status.HTTP_201_CREATED)
async def create_browser_task(
    payload: BrowserTaskCreate,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    try:
        return _task_read(await service.create(payload))
    except BrowserTaskActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/campaign",
    response_model=BrowserTaskCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign_browser_tasks(
    payload: BrowserTaskCampaignCreate,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskCampaignResponse:
    try:
        result = await service.create_for_campaign(payload)
    except BrowserTaskActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BrowserTaskCampaignResponse(
        campaign_id=result.campaign_id,
        queued_count=result.queued_count,
        created_count=len(result.created),
        reused_count=len(result.reused),
        failed_count=len(result.failures),
        items=[_task_read(task) for task in result.tasks],
        failures=[
            BrowserTaskCampaignFailure(application_id=application_id, reason=reason)
            for application_id, reason in result.failures
        ],
    )


@router.get("/platforms", response_model=list[PlatformAdapterRead])
async def list_platform_adapters(
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> list[PlatformAdapterRead]:
    return [PlatformAdapterRead.model_validate(item) for item in service.adapters.catalog()]


@router.get("/{task_id}", response_model=BrowserTaskRead)
async def get_browser_task(
    task_id: UUID,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    try:
        return _task_read(await service.get_task(task_id))
    except BrowserTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _task_action(task_id: UUID, action, service: BrowserTaskService) -> BrowserTaskRead:
    try:
        return _task_read(await action(task_id))
    except BrowserTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BrowserTaskActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/start", response_model=BrowserTaskRead)
async def start_browser_task(
    task_id: UUID,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    return await _task_action(task_id, service.start, service)


@router.post("/{task_id}/cancel", response_model=BrowserTaskRead)
async def cancel_browser_task(
    task_id: UUID,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    return await _task_action(task_id, service.cancel, service)


@router.post("/{task_id}/resume", response_model=BrowserTaskRead)
async def resume_browser_task(
    task_id: UUID,
    payload: BrowserTaskResumeRequest,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    try:
        return _task_read(await service.resume(task_id, payload))
    except BrowserTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BrowserTaskActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/mock-extension", response_model=BrowserTaskRead)
async def simulate_browser_extension(
    task_id: UUID,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> BrowserTaskRead:
    try:
        return _task_read(await service.simulate_extension(task_id))
    except BrowserTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BrowserTaskActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{task_id}/events/stream")
async def stream_browser_task_events(
    task_id: UUID,
    service: BrowserTaskService = Depends(get_browser_task_service),
) -> StreamingResponse:
    try:
        await service.get_task(task_id)
    except BrowserTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        delivered: set[UUID] = set()
        terminal = {
            BrowserTaskStatus.COMPLETED.value,
            BrowserTaskStatus.CANCELLED.value,
            BrowserTaskStatus.FAILED.value,
            BrowserTaskStatus.WAITING_FOR_USER.value,
        }
        while True:
            task = await service.get_task(task_id)
            pending = [
                event
                for event in sorted(task.events, key=lambda item: item.created_at)
                if event.id not in delivered
            ]
            for event in pending:
                delivered.add(event.id)
                payload = _event_read(event).model_dump(mode="json")
                yield f"id: {event.id}\ndata: {json.dumps(payload)}\n\n"
            if task.status in terminal and not pending:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.websocket("/ws/{task_id}")
async def browser_task_socket(
    websocket: WebSocket,
    task_id: UUID,
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> None:
    await websocket.accept()
    service = BrowserTaskService(session, provider)
    try:
        hello_message = await websocket.receive_json()
        hello = (
            BrowserExtensionHello.model_validate(hello_message)
            if hello_message.get("type") == "EXTENSION_HELLO"
            else None
        )
        await service.connect_extension(task_id, websocket, hello)
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "ACTION_RESULT":
                continue
            result = BrowserActionResult.model_validate(message)
            await service.handle_action_result(task_id, result)
    except WebSocketDisconnect:
        browser_socket_manager.disconnect(task_id, websocket)
    except (BrowserTaskActionError, BrowserTaskNotFoundError) as exc:
        browser_socket_manager.disconnect(task_id, websocket)
        await websocket.close(code=1008, reason=str(exc))
