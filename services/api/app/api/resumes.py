from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.dependencies import get_resume_service
from app.core.config import get_settings
from app.schemas.resumes import (
    ResumeChunkRead,
    ResumeListResponse,
    ResumeProfile,
    ResumeRead,
    ResumeUpdate,
)
from app.services.resume_parsing import ResumeFileError
from app.services.resumes import (
    ResumeDefaultError,
    ResumeInUseError,
    ResumeNotFoundError,
    ResumeService,
    ResumeUserNotFoundError,
    resume_chunk_embedding_dimensions,
)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def _resume_read(resume) -> ResumeRead:
    profile = ResumeProfile.model_validate(resume.structured_profile or {})
    return ResumeRead(
        id=resume.id,
        user_id=resume.user_id,
        name=resume.name,
        original_filename=resume.original_filename,
        raw_text=resume.raw_text,
        structured_profile=profile,
        version=resume.version,
        is_default=resume.is_default,
        chunk_count=len(resume.chunks),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


@router.post("", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: Annotated[UploadFile, File(...)],
    name: Annotated[str | None, Form(max_length=200)] = None,
    user_id: Annotated[UUID | None, Form()] = None,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeRead:
    data = await file.read(get_settings().max_upload_size_bytes + 1)
    if len(data) > get_settings().max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Resume file is too large"
        )
    try:
        resume = await service.upload(
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            name=name,
            user_id=user_id,
        )
    except ResumeFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except ResumeUserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _resume_read(resume)


@router.post("/{resume_id}/parse", response_model=ResumeRead)
async def parse_resume(
    resume_id: UUID, service: ResumeService = Depends(get_resume_service)
) -> ResumeRead:
    try:
        resume = await service.parse_existing(resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _resume_read(resume)


@router.get("", response_model=ResumeListResponse)
async def list_resumes(
    user_id: UUID | None = Query(default=None),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeListResponse:
    resumes, total = await service.list_resumes(user_id=user_id)
    return ResumeListResponse(items=[_resume_read(resume) for resume in resumes], total=total)


@router.get("/{resume_id}", response_model=ResumeRead)
async def get_resume(
    resume_id: UUID, service: ResumeService = Depends(get_resume_service)
) -> ResumeRead:
    try:
        resume = await service.get_resume(resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _resume_read(resume)


@router.get("/{resume_id}/chunks", response_model=list[ResumeChunkRead])
async def get_resume_chunks(
    resume_id: UUID, service: ResumeService = Depends(get_resume_service)
) -> list[ResumeChunkRead]:
    try:
        chunks = await service.get_chunks(resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        ResumeChunkRead(
            id=chunk.id,
            resume_id=chunk.resume_id,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            metadata=chunk.chunk_metadata,
            embedding_dimensions=resume_chunk_embedding_dimensions(chunk),
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]


@router.patch("/{resume_id}", response_model=ResumeRead)
async def update_resume(
    resume_id: UUID,
    payload: ResumeUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeRead:
    try:
        return _resume_read(await service.update_resume(resume_id, payload))
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ResumeDefaultError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: UUID,
    service: ResumeService = Depends(get_resume_service),
) -> None:
    try:
        await service.delete_resume(resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ResumeInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
