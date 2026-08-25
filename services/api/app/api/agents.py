import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent_runtime
from app.models.entities import AgentEvent, AgentRun, AgentStep
from app.models.states import AgentRunStatus
from app.schemas.agents import (
    AgentEventRead,
    AgentRunCreate,
    AgentRunListResponse,
    AgentRunRead,
    AgentRunResumeRequest,
    AgentStepRead,
    AgentToolRead,
)
from app.services.agent_runtime import AgentRunActionError, AgentRunNotFoundError, AgentRuntime

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])


def _step_read(step: AgentStep) -> AgentStepRead:
    return AgentStepRead(
        id=step.id,
        run_id=step.run_id,
        sequence=step.sequence,
        step_type=step.step_type,
        tool_name=step.tool_name,
        input=step.step_input,
        output=step.step_output,
        status=step.status,
        attempt=step.attempt,
        latency_ms=step.latency_ms,
        error=step.error,
        created_at=step.created_at,
    )


def _event_read(event: AgentEvent) -> AgentEventRead:
    return AgentEventRead(
        id=event.id,
        run_id=event.run_id,
        event_type=event.event_type,
        payload=event.payload,
        created_at=event.created_at,
    )


def _run_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        id=run.id,
        user_id=run.user_id,
        campaign_id=run.campaign_id,
        agent_type=run.agent_type,
        status=run.status,
        input=run.run_input,
        output=run.run_output,
        state=run.agent_state,
        memory=run.memory,
        max_steps=run.max_steps,
        timeout_seconds=run.timeout_seconds,
        max_retries=run.max_retries,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        steps=[
            _step_read(item)
            for item in sorted(run.steps, key=lambda value: value.sequence)
        ],
        events=[
            _event_read(item)
            for item in sorted(run.events, key=lambda value: value.created_at)
        ],
    )


@router.get("", response_model=AgentRunListResponse)
async def list_agent_runs(
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunListResponse:
    runs, total = await runtime.list_runs()
    return AgentRunListResponse(items=[_run_read(run) for run in runs], total=total)


@router.post("", response_model=AgentRunRead, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreate,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    try:
        return _run_read(await runtime.create(payload))
    except AgentRunActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/tools", response_model=list[AgentToolRead])
async def list_agent_tools(
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> list[AgentToolRead]:
    return [
        AgentToolRead(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema.model_json_schema(),
            output_schema=tool.output_schema.model_json_schema(),
        )
        for tool in runtime.registry.catalog()
    ]


@router.get("/{run_id}", response_model=AgentRunRead)
async def get_agent_run(
    run_id: UUID,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    try:
        return _run_read(await runtime.get_run(run_id))
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _run_action(run_id: UUID, action, runtime: AgentRuntime) -> AgentRunRead:
    try:
        return _run_read(await action(run_id))
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentRunActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{run_id}/start", response_model=AgentRunRead)
async def start_agent_run(
    run_id: UUID,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    return await _run_action(run_id, runtime.start, runtime)


@router.post("/{run_id}/pause", response_model=AgentRunRead)
async def pause_agent_run(
    run_id: UUID,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    return await _run_action(run_id, runtime.pause, runtime)


@router.post("/{run_id}/resume", response_model=AgentRunRead)
async def resume_agent_run(
    run_id: UUID,
    payload: AgentRunResumeRequest | None = None,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    try:
        return _run_read(await runtime.resume(run_id, payload or AgentRunResumeRequest()))
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentRunActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{run_id}/cancel", response_model=AgentRunRead)
async def cancel_agent_run(
    run_id: UUID,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> AgentRunRead:
    return await _run_action(run_id, runtime.cancel, runtime)


@router.get("/{run_id}/events/stream")
async def stream_agent_events(
    run_id: UUID,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> StreamingResponse:
    try:
        await runtime.get_run(run_id)
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        delivered: set[UUID] = set()
        terminal = {
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.CANCELLED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.TIMED_OUT.value,
            AgentRunStatus.WAITING_FOR_USER.value,
        }
        while True:
            run = await runtime.get_run(run_id)
            pending = [
                event
                for event in sorted(run.events, key=lambda value: value.created_at)
                if event.id not in delivered
            ]
            for event in pending:
                delivered.add(event.id)
                payload = _event_read(event).model_dump(mode="json")
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(payload)}\n\n"
            if run.status in terminal and not pending:
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
