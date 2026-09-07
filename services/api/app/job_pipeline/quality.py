from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobQuality:
    score: float
    level: str
    details: dict[str, Any]


def evaluate_quality(
    *,
    title: str,
    description: str,
    company: str,
    location: str,
    salary: dict[str, Any],
    education: str,
    experience: str,
    responsibilities: list[str],
    requirements: list[str],
    skills: list[dict[str, str]],
    valid_evidence: int,
    evidence_count: int,
) -> JobQuality:
    checks = {
        "title": bool(title),
        "description": len(description) >= 80,
        "company": bool(company),
        "location": bool(location),
        "salary": salary.get("status") in {"parsed", "negotiable"},
        "education": bool(education),
        "experience": bool(experience),
        "responsibilities": bool(responsibilities),
        "requirements": bool(requirements),
        "skills": bool(skills),
        "evidence": evidence_count == 0 or valid_evidence / evidence_count >= 0.8,
    }
    weights = {
        "title": 0.08,
        "description": 0.18,
        "company": 0.08,
        "location": 0.08,
        "salary": 0.10,
        "education": 0.08,
        "experience": 0.08,
        "responsibilities": 0.12,
        "requirements": 0.12,
        "skills": 0.05,
        "evidence": 0.03,
    }
    score = round(sum(weights[key] for key, value in checks.items() if value), 3)
    level = "high" if score >= 0.8 else "medium" if score >= 0.55 else "low"
    return JobQuality(score=score, level=level, details={"checks": checks, "weights": weights})
