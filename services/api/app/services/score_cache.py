from __future__ import annotations

import hashlib
import json

from app.llm.provider import LLMProvider
from app.models.entities import Job, Resume


def build_score_fingerprint(
    *,
    job: Job,
    resume: Resume,
    provider: LLMProvider,
    score_version: str,
    weights: dict[str, float],
) -> str:
    """Identify every input that can materially change a persisted score."""

    payload = {
        "job_id": str(job.id),
        "job_content_hash": job.content_hash,
        "job_updated_at": job.updated_at.isoformat(),
        "resume_id": str(resume.id),
        "resume_version": resume.version,
        "resume_updated_at": resume.updated_at.isoformat(),
        "provider": getattr(provider, "provider_name", provider.__class__.__name__),
        "model": getattr(provider, "model", None),
        "base_url": getattr(provider, "base_url", None),
        "score_version": score_version,
        "weights": weights,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
