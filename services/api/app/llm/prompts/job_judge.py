from __future__ import annotations

from app.schemas.matching import ResumeEvidenceRead

JOB_JUDGE_V1 = "JOB_JUDGE_V1"


def build_job_judge_prompt(
    *,
    job_summary: str,
    required_skills: list[str],
    evidence: list[ResumeEvidenceRead],
    sub_scores: dict[str, float],
) -> str:
    evidence_text = (
        "\n".join(f"[{item.chunk_type}] {item.content}" for item in evidence)
        or "No relevant resume evidence was retrieved."
    )
    return f"""Prompt version: {JOB_JUDGE_V1}
Evaluate job fit using only the supplied resume evidence.
Do not infer facts not present in evidence.

Job summary:
{job_summary}

Required skills: {", ".join(required_skills) or "Not specified"}
Deterministic sub-scores: {sub_scores}

Retrieved resume evidence:
{evidence_text}

Return a structured score, strengths, gaps, risks, recommendation,
and a concise user-visible reasoning summary.
"""
