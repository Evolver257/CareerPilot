from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from evaluation.rag_v2.annotations import AnnotationStore
from evaluation.rag_v2.schemas import Adjudication, RAGAnnotation

DATASET_DIR = Path(__file__).parents[2] / "evaluation" / "datasets" / "rag_v2"
router = APIRouter(prefix="/api/evaluation-v2", tags=["rag-evaluation-v2"])


def _read_jsonl(name: str) -> list[dict[str, Any]]:
    path = DATASET_DIR / name
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _store() -> AnnotationStore:
    return AnnotationStore(DATASET_DIR / "annotations.jsonl", DATASET_DIR / "adjudications.jsonl")


def _dataset_version() -> str:
    path = DATASET_DIR / "corpus_manifest.json"
    if not path.exists():
        return "rag-v2.0.0"
    return str(json.loads(path.read_text(encoding="utf-8")).get("dataset_version", "rag-v2.0.0"))


def _safe_annotator(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,120}", value, re.UNICODE):
        raise HTTPException(
            status_code=422, detail="annotator_id 只允许字母、数字、下划线、连字符或中文"
        )
    return value


class AnnotationPayload(BaseModel):
    dataset_version: str
    query_id: str
    job_id: str
    annotator_id: str = Field(min_length=1, max_length=120)
    relevance_grade: int = Field(ge=-1, le=3)
    hard_constraint_violation: str = "uncertain"
    answerability_judgment: str | None = None
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "medium"
    annotation_note: str = ""
    status: str = "draft"


def _validate_pair(
    query_id: str, job_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    queries = {str(row["query_id"]): row for row in _read_jsonl("queries.jsonl")}
    jobs = {str(row["job_id"]): row for row in _read_jsonl("corpus.jsonl")}
    candidates = [
        row
        for row in _read_jsonl("candidate_pool.jsonl")
        if str(row.get("query_id")) == query_id and str(row.get("job_id")) == job_id
    ]
    if query_id not in queries or job_id not in jobs or not candidates:
        raise HTTPException(status_code=404, detail="query/job 不在 V2 候选池中")
    return queries[query_id], jobs[job_id], candidates[0]


@router.get("/status")
async def status() -> dict[str, Any]:
    manifest_path = DATASET_DIR / "corpus_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    queries = _read_jsonl("queries.jsonl")
    candidates = _read_jsonl("candidate_pool.jsonl")
    candidate_pairs = len(candidates)
    store = _store()
    return {
        "dataset_version": manifest.get("dataset_version", "rag-v2.0.0"),
        "label_status": "stable_gold"
        if store.quality(total_pairs=candidate_pairs).get("stable_gold")
        else "awaiting_review",
        "corpus_sha256": manifest.get("corpus_sha256"),
        "source_job_count": manifest.get("source_job_count", 0),
        "selected_job_count": manifest.get("selected_job_count", 0),
        "query_count": len(queries),
        "candidate_pair_count": candidate_pairs,
        "annotation_quality": store.quality(total_pairs=candidate_pairs),
        "progress": {
            "annotator_a": store.progress("annotator_a", candidate_pairs),
            "annotator_b": store.progress("annotator_b", candidate_pairs),
        },
    }


@router.get("/queries")
async def list_queries(
    annotator_id: str = Query(default="annotator_a", min_length=1, max_length=120),
) -> list[dict[str, Any]]:
    annotator_id = _safe_annotator(annotator_id)
    rows = _read_jsonl("queries.jsonl")
    candidates = _read_jsonl("candidate_pool.jsonl")
    counts: dict[str, int] = {}
    for row in candidates:
        counts[str(row["query_id"])] = counts.get(str(row["query_id"]), 0) + 1
    store = _store()
    result = []
    for row in rows:
        saved = [
            item
            for item in store.annotations()
            if item.get("annotator_id") == annotator_id and item.get("query_id") == row["query_id"]
        ]
        result.append(
            {
                **row,
                "candidate_count": counts.get(str(row["query_id"]), 0),
                "annotated_count": len(saved),
                "submitted_count": sum(item.get("status") == "submitted" for item in saved),
            }
        )
    return result


@router.get("/queries/{query_id}")
async def get_query(
    query_id: str,
    annotator_id: str = Query(default="annotator_a", min_length=1, max_length=120),
) -> dict[str, Any]:
    annotator_id = _safe_annotator(annotator_id)
    queries = {str(row["query_id"]): row for row in _read_jsonl("queries.jsonl")}
    if query_id not in queries:
        raise HTTPException(status_code=404, detail="query 不存在")
    jobs = {str(row["job_id"]): row for row in _read_jsonl("corpus.jsonl")}
    candidates = sorted(
        (row for row in _read_jsonl("candidate_pool.jsonl") if str(row["query_id"]) == query_id),
        key=lambda row: row.get("candidate_rank", 0),
    )
    store = _store()
    items = []
    for candidate in candidates:
        job = jobs.get(str(candidate["job_id"]))
        if not job:
            continue
        # Deliberately omit channel_scores and channel_ranks from the labeler view.
        public_job = {
            key: value
            for key, value in job.items()
            if key not in {"dedup_keys", "normalized_fields", "content_sha256", "jd_simhash"}
        }
        items.append(
            {
                "job": public_job,
                "candidate_rank": candidate.get("candidate_rank"),
                "channels": candidate.get("channels", []),
                "annotation": store.get(annotator_id, query_id, str(candidate["job_id"])),
            }
        )
    return {"query": queries[query_id], "items": items, "labeler_view": {"model_scores": False}}


@router.post("/annotations")
async def save_annotation(payload: AnnotationPayload) -> dict[str, Any]:
    _validate_pair(payload.query_id, payload.job_id)
    if payload.dataset_version != _dataset_version():
        raise HTTPException(status_code=422, detail="dataset_version 与当前 V2 快照不一致")
    value = RAGAnnotation.model_validate(payload.model_dump())
    return _store().upsert(value)


@router.post("/adjudications")
async def save_adjudication(payload: Adjudication) -> dict[str, Any]:
    _validate_pair(payload.query_id, payload.job_id)
    if payload.dataset_version != _dataset_version():
        raise HTTPException(status_code=422, detail="dataset_version 与当前 V2 快照不一致")
    return _store().adjudicate(payload)


@router.get("/export/annotations.jsonl", response_class=PlainTextResponse)
async def export_annotations() -> PlainTextResponse:
    body = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in _store().annotations()
    )
    return PlainTextResponse(
        body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=annotations.jsonl"},
    )


@router.get("/export/adjudications.jsonl", response_class=PlainTextResponse)
async def export_adjudications() -> PlainTextResponse:
    body = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in _store().adjudications()
    )
    return PlainTextResponse(
        body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=adjudications.jsonl"},
    )
