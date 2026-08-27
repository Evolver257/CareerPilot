from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_career_advisor_service
from app.models.entities import CareerAdvisorCitation, CareerAdvisorMessage, CareerAdvisorSession
from app.schemas.career_advisor import (
    CareerAdvisorCitationListResponse,
    CareerAdvisorCitationRead,
    CareerAdvisorMessageCreate,
    CareerAdvisorMessageRead,
    CareerAdvisorRoleComparisonRequest,
    CareerAdvisorSessionCreate,
    CareerAdvisorSessionListResponse,
    CareerAdvisorSessionRead,
    CareerAdvisorSessionUpdate,
)
from app.schemas.knowledge_search import (
    JobKnowledgeSearchRequest,
    JobKnowledgeSearchResponse,
    JobKnowledgeStatistics,
)
from app.services.career_advisor import (
    CareerAdvisorActionError,
    CareerAdvisorNotFoundError,
    CareerAdvisorService,
    cancel_career_message_task,
    register_career_message_task,
    unregister_career_message_task,
)
from app.services.job_knowledge_rag import KnowledgeRetrievalError

router = APIRouter(prefix="/api/career-advisor", tags=["career-advisor"])


def _citation_read(citation: CareerAdvisorCitation) -> CareerAdvisorCitationRead:
    return CareerAdvisorCitationRead(
        id=citation.id,
        message_id=citation.message_id,
        job_id=citation.job_id,
        chunk_id=citation.chunk_id,
        citation_index=citation.citation_index,
        evidence=citation.evidence,
        metadata=citation.citation_metadata,
        created_at=citation.created_at,
    )


def _message_read(message: CareerAdvisorMessage) -> CareerAdvisorMessageRead:
    return CareerAdvisorMessageRead(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        status=message.status,
        intent=message.intent,
        model_provider=message.model_provider,
        model_name=message.model_name,
        token_usage=message.token_usage,
        tool_trace=message.tool_trace,
        answer_metadata=message.answer_metadata,
        latency_ms=message.latency_ms,
        error_message=message.error_message,
        created_at=message.created_at,
        updated_at=message.updated_at,
        citations=[_citation_read(item) for item in message.citations],
    )


def _session_read(session: CareerAdvisorSession) -> CareerAdvisorSessionRead:
    from app.schemas.knowledge_search import JobKnowledgeFilters

    return CareerAdvisorSessionRead(
        id=session.id,
        user_id=session.user_id,
        resume_id=session.resume_id,
        title=session.title,
        agent_type=session.agent_type,
        context_filters=JobKnowledgeFilters.model_validate(session.context_filters or {}),
        summary=session.summary,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            _message_read(item)
            for item in sorted(session.messages, key=lambda value: value.created_at)
        ],
    )


def _not_found(exc: CareerAdvisorNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _action_error(exc: CareerAdvisorActionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/jobs/search", response_model=JobKnowledgeSearchResponse)
async def search_career_advisor_jobs(
    payload: JobKnowledgeSearchRequest,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> JobKnowledgeSearchResponse:
    try:
        return await service.tools.search_job_knowledge(
            payload.query,
            payload.filters,
            resume_id=payload.resume_id,
            request=payload,
        )
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/market/aggregate", response_model=JobKnowledgeStatistics)
async def aggregate_career_advisor_market(
    payload: JobKnowledgeSearchRequest,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> JobKnowledgeStatistics:
    try:
        result = await service.tools.aggregate_job_market(payload.query, payload.filters)
        return JobKnowledgeStatistics.model_validate(result)
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/resume-gap")
async def analyze_career_advisor_resume_gap(
    payload: JobKnowledgeSearchRequest,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> dict:
    try:
        resume_id = await service.resolve_resume_id(payload.resume_id)
        return await service.tools.analyze_resume_gap(
            payload.query, payload.filters, resume_id
        )
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/role-comparison")
async def compare_career_advisor_roles(
    payload: CareerAdvisorRoleComparisonRequest,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> dict:
    try:
        return await service.tools.compare_role_profiles(payload.queries, payload.filters)
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/job-coverage")
async def estimate_career_advisor_coverage(
    payload: JobKnowledgeSearchRequest,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> dict:
    try:
        resume_id = await service.resolve_resume_id(payload.resume_id)
        return await service.tools.estimate_job_coverage(
            payload.query, payload.filters, resume_id
        )
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/sessions", response_model=CareerAdvisorSessionListResponse)
async def list_career_advisor_sessions(
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorSessionListResponse:
    sessions, total = await service.list_sessions()
    return CareerAdvisorSessionListResponse(
        items=[_session_read(item) for item in sessions], total=total
    )


@router.post(
    "/sessions",
    response_model=CareerAdvisorSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_career_advisor_session(
    payload: CareerAdvisorSessionCreate,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorSessionRead:
    try:
        return _session_read(await service.create_session(payload))
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc


@router.get("/sessions/{session_id}", response_model=CareerAdvisorSessionRead)
async def get_career_advisor_session(
    session_id: UUID,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorSessionRead:
    try:
        return _session_read(await service.get_session(session_id))
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/sessions/{session_id}", response_model=CareerAdvisorSessionRead)
async def update_career_advisor_session(
    session_id: UUID,
    payload: CareerAdvisorSessionUpdate,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorSessionRead:
    try:
        return _session_read(await service.update_session(session_id, payload))
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_career_advisor_session(
    session_id: UUID,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> Response:
    try:
        await service.delete_session(session_id)
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=CareerAdvisorMessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def send_career_advisor_message(
    session_id: UUID,
    payload: CareerAdvisorMessageCreate,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorMessageRead:
    try:
        return _message_read(await service.send_message(session_id, payload))
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc


def _sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages/stream")
async def stream_career_advisor_message(
    session_id: UUID,
    payload: CareerAdvisorMessageCreate,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> StreamingResponse:
    try:
        pending = await service.create_pending_message(session_id, payload)
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc

    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    async def on_event(event_type: str, event_payload: dict) -> None:
        await queue.put((event_type, event_payload))

    async def run() -> None:
        await service.process_message(pending.id, on_event=on_event)

    task = asyncio.create_task(run())
    register_career_message_task(pending.id, task)

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield _sse("message_started", {"message_id": str(pending.id)})
            while True:
                try:
                    event_type, event_payload = await asyncio.wait_for(queue.get(), 0.25)
                except TimeoutError:
                    if task.done():
                        break
                    yield ": heartbeat\n\n"
                    continue
                yield _sse(event_type, event_payload)

            while not queue.empty():
                event_type, event_payload = queue.get_nowait()
                yield _sse(event_type, event_payload)
            if task.cancelled():
                yield _sse("message_cancelled", {"message_id": str(pending.id)})
            else:
                await task
                completed = await service.get_message(pending.id)
                yield _sse("message_state", _message_read(completed).model_dump(mode="json"))
        except asyncio.CancelledError:
            await cancel_career_message_task(pending.id)
            raise
        finally:
            unregister_career_message_task(pending.id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/cancel", response_model=CareerAdvisorMessageRead)
async def cancel_career_advisor_message(
    message_id: UUID,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorMessageRead:
    try:
        await cancel_career_message_task(message_id)
        return _message_read(await service.cancel_message(message_id))
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/messages/{message_id}/regenerate", response_model=CareerAdvisorMessageRead)
async def regenerate_career_advisor_message(
    message_id: UUID,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorMessageRead:
    try:
        return _message_read(await service.regenerate(message_id))
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    except CareerAdvisorActionError as exc:
        raise _action_error(exc) from exc


@router.get(
    "/messages/{message_id}/citations",
    response_model=CareerAdvisorCitationListResponse,
)
async def list_career_advisor_citations(
    message_id: UUID,
    service: CareerAdvisorService = Depends(get_career_advisor_service),
) -> CareerAdvisorCitationListResponse:
    try:
        message = await service.get_message(message_id)
    except CareerAdvisorNotFoundError as exc:
        raise _not_found(exc) from exc
    citations = sorted(message.citations, key=lambda item: item.citation_index)
    return CareerAdvisorCitationListResponse(
        items=[_citation_read(item) for item in citations], total=len(citations)
    )
