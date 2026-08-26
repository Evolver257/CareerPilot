from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_job_service,
    get_matching_service,
    get_ranking_run_service,
    get_ranking_service,
)
from app.schemas.job_intelligence import (
    JobAnalysisRead,
    JobImportRequest,
    JobImportResponse,
    JobRequirements,
    JobSkillRead,
    StructuredJob,
)
from app.schemas.jobs import JobCreate, JobListResponse, JobRead, JobUpdate
from app.schemas.matching import JobScoreRead, JobScoreRequest
from app.schemas.ranking import JobRankingRequest, JobRankingResponse, RankingRunRead
from app.services.jobs import (
    DuplicateJobError,
    InvalidJobImportError,
    JobInUseError,
    JobNotFoundError,
    JobService,
)
from app.services.matching import (
    MatchingJobNotFoundError,
    MatchingResumeNotFoundError,
    MatchingService,
)
from app.services.ranking import RankingService
from app.services.ranking_runs import (
    RankingRunNotFoundError,
    RankingRunNotReadyError,
    RankingRunService,
    execute_ranking_run,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _analysis_read(job) -> JobAnalysisRead:
    normalized = job.normalized_data or {}
    structured = StructuredJob.model_validate(normalized.get("structured_job", {}))
    if not structured.title:
        structured = structured.model_copy(
            update={
                "title": job.title,
                "location": job.location or "",
                "job_type": job.job_type or "",
            }
        )
    requirements = JobRequirements.model_validate(normalized.get("requirements", {}))
    if not requirements.education and job.education_requirement:
        requirements = requirements.model_copy(update={"education": job.education_requirement})
    if not requirements.experience and job.experience_requirement:
        requirements = requirements.model_copy(update={"experience": job.experience_requirement})
    skills = [JobSkillRead.model_validate(skill) for skill in job.skills]
    return JobAnalysisRead(
        job=JobRead.model_validate(job),
        structured_job=structured,
        requirements=requirements,
        skills=skills,
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    service: JobService = Depends(get_job_service),
) -> JobListResponse:
    jobs, total = await service.list_jobs(page=page, page_size=page_size, search=search)
    return JobListResponse(items=jobs, total=total, page=page, page_size=page_size)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, service: JobService = Depends(get_job_service)) -> JobRead:
    try:
        return await service.create_job(payload)
    except DuplicateJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/import", response_model=JobImportResponse, status_code=status.HTTP_201_CREATED)
async def import_jobs(
    payload: JobImportRequest, service: JobService = Depends(get_job_service)
) -> JobImportResponse:
    try:
        result = await service.import_jobs(payload)
    except (DuplicateJobError, InvalidJobImportError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return JobImportResponse(
        items=[_analysis_read(job) for job in result.jobs],
        created=result.created,
        duplicates=result.duplicates,
        total=len(result.jobs),
    )


@router.post("/rank", response_model=JobRankingResponse)
async def rank_jobs(
    payload: JobRankingRequest,
    service: RankingService = Depends(get_ranking_service),
) -> JobRankingResponse:
    try:
        return await service.rank(payload)
    except MatchingResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/rank-runs",
    response_model=RankingRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ranking_run(
    payload: JobRankingRequest,
    background_tasks: BackgroundTasks,
    service: RankingRunService = Depends(get_ranking_run_service),
) -> RankingRunRead:
    try:
        run = await service.create(payload)
    except MatchingResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    background_tasks.add_task(execute_ranking_run, run.id)
    return RankingRunRead.model_validate(run)


@router.get("/rank-runs/{run_id}", response_model=RankingRunRead)
async def get_ranking_run(
    run_id: UUID,
    service: RankingRunService = Depends(get_ranking_run_service),
) -> RankingRunRead:
    try:
        return RankingRunRead.model_validate(await service.get(run_id))
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/rank-runs/{run_id}/result", response_model=JobRankingResponse)
async def get_ranking_run_result(
    run_id: UUID,
    service: RankingRunService = Depends(get_ranking_run_service),
) -> JobRankingResponse:
    try:
        return await service.get_result(run_id)
    except RankingRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RankingRunNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/analyze", response_model=JobAnalysisRead)
async def analyze_job(
    job_id: UUID, service: JobService = Depends(get_job_service)
) -> JobAnalysisRead:
    job = await service.analyze_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _analysis_read(job)


@router.post("/{job_id}/score", response_model=JobScoreRead)
async def score_job(
    job_id: UUID,
    payload: JobScoreRequest | None = None,
    service: MatchingService = Depends(get_matching_service),
) -> JobScoreRead:
    try:
        score = await service.score(
            job_id=job_id,
            resume_id=payload.resume_id if payload else None,
            force=payload.force if payload else False,
        )
    except MatchingJobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MatchingResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return JobScoreRead.model_validate(score)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: UUID, service: JobService = Depends(get_job_service)) -> JobRead:
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: UUID,
    payload: JobUpdate,
    service: JobService = Depends(get_job_service),
) -> JobRead:
    try:
        return await service.update_job(job_id, payload)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> None:
    try:
        await service.delete_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JobInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
