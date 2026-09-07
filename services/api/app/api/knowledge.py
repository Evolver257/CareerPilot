from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_job_knowledge_rag,
    get_knowledge_index_service,
    get_llm_provider,
)
from app.llm.provider import LLMProvider
from app.models.entities import KnowledgeIndexRun, KnowledgeIndexRunItem
from app.schemas.knowledge import (
    KnowledgeHealthRead,
    KnowledgeIndexRunCreate,
    KnowledgeIndexRunItemListResponse,
    KnowledgeIndexRunItemRead,
    KnowledgeIndexRunListResponse,
    KnowledgeIndexRunRead,
)
from app.schemas.knowledge_search import (
    AgenticRAGSearchResponse,
    JobKnowledgeSearchRequest,
    JobKnowledgeSearchResponse,
    JobKnowledgeStatistics,
)
from app.services.agentic_rag import AgenticRAGPipeline
from app.services.job_knowledge_rag import (
    JobKnowledgeRAG,
    KnowledgeEmbeddingUnavailableError,
    KnowledgeRetrievalError,
)
from app.services.knowledge_indexing import (
    KnowledgeIndexActionError,
    KnowledgeIndexNotFoundError,
    KnowledgeIndexService,
    schedule_knowledge_index,
    stop_knowledge_index,
)

router = APIRouter(prefix="/api/knowledge", tags=["job-knowledge"])


@router.get("/status", response_model=KnowledgeHealthRead)
async def knowledge_status(
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeHealthRead:
    return KnowledgeHealthRead.model_validate(await service.health())


def _run_read(run: KnowledgeIndexRun) -> KnowledgeIndexRunRead:
    return KnowledgeIndexRunRead(
        id=run.id,
        mode=run.mode,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        total_jobs=run.total_jobs,
        processed_jobs=run.processed_jobs,
        succeeded_jobs=run.succeeded_jobs,
        skipped_jobs=run.skipped_jobs,
        failed_jobs=run.failed_jobs,
        current_job_id=run.current_job_id,
        request=run.request_payload,
        result=run.result_payload,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _item_read(item: KnowledgeIndexRunItem) -> KnowledgeIndexRunItemRead:
    return KnowledgeIndexRunItemRead(
        id=item.id,
        run_id=item.run_id,
        job_id=item.job_id,
        status=item.status,
        chunk_count=item.chunk_count,
        reused_embedding_count=item.reused_embedding_count,
        error=item.error,
        started_at=item.started_at,
        finished_at=item.finished_at,
        created_at=item.created_at,
    )


@router.post("/search", response_model=JobKnowledgeSearchResponse)
async def search_job_knowledge(
    payload: JobKnowledgeSearchRequest,
    service: JobKnowledgeRAG = Depends(get_job_knowledge_rag),
) -> JobKnowledgeSearchResponse:
    try:
        return await service.search(payload)
    except KnowledgeEmbeddingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/agentic-search", response_model=AgenticRAGSearchResponse)
async def search_job_knowledge_agentic(
    payload: JobKnowledgeSearchRequest,
    service: JobKnowledgeRAG = Depends(get_job_knowledge_rag),
    provider: LLMProvider = Depends(get_llm_provider),
) -> AgenticRAGSearchResponse:
    try:
        return await AgenticRAGPipeline(service, llm_provider=provider).run(payload)
    except KnowledgeEmbeddingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/statistics", response_model=JobKnowledgeStatistics)
async def get_job_knowledge_statistics(
    payload: JobKnowledgeSearchRequest,
    service: JobKnowledgeRAG = Depends(get_job_knowledge_rag),
) -> JobKnowledgeStatistics:
    try:
        return await service.statistics(payload)
    except KnowledgeRetrievalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/index-runs", response_model=KnowledgeIndexRunListResponse)
async def list_knowledge_index_runs(
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunListResponse:
    runs, total = await service.list_runs()
    return KnowledgeIndexRunListResponse(items=[_run_read(run) for run in runs], total=total)


@router.post(
    "/index-runs",
    response_model=KnowledgeIndexRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_knowledge_index_run(
    payload: KnowledgeIndexRunCreate,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunRead:
    try:
        run = await service.create(payload)
    except KnowledgeIndexActionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if payload.auto_start and run.status == "PENDING":
        schedule_knowledge_index(run.id)
    return _run_read(run)


@router.get("/index-runs/{run_id}", response_model=KnowledgeIndexRunRead)
async def get_knowledge_index_run(
    run_id: UUID,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunRead:
    try:
        return _run_read(await service.get_run(run_id))
    except KnowledgeIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/index-runs/{run_id}/items",
    response_model=KnowledgeIndexRunItemListResponse,
)
async def list_knowledge_index_run_items(
    run_id: UUID,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunItemListResponse:
    try:
        items, total = await service.list_items(run_id)
    except KnowledgeIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return KnowledgeIndexRunItemListResponse(
        items=[_item_read(item) for item in items], total=total
    )


@router.post("/index-runs/{run_id}/start", response_model=KnowledgeIndexRunRead)
async def start_knowledge_index_run(
    run_id: UUID,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunRead:
    try:
        run = await service.get_run(run_id)
    except KnowledgeIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if run.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务当前不可启动")
    from app.services.work_queue import enqueue_work

    await enqueue_work(service.session, "knowledge", run.id, retry=True)
    await service.session.commit()
    schedule_knowledge_index(run.id)
    return _run_read(run)


@router.post("/index-runs/{run_id}/cancel", response_model=KnowledgeIndexRunRead)
async def cancel_knowledge_index_run(
    run_id: UUID,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunRead:
    try:
        run = await service.cancel(run_id)
    except KnowledgeIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    stop_knowledge_index(run_id)
    return _run_read(run)


@router.post("/index-runs/{run_id}/retry", response_model=KnowledgeIndexRunRead)
async def retry_knowledge_index_run(
    run_id: UUID,
    service: KnowledgeIndexService = Depends(get_knowledge_index_service),
) -> KnowledgeIndexRunRead:
    try:
        run = await service.retry(run_id)
    except KnowledgeIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KnowledgeIndexActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    schedule_knowledge_index(run.id)
    return _run_read(run)
