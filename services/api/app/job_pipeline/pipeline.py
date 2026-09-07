from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.job_pipeline.cleaners import clean_job_text
from app.job_pipeline.contracts import EvidenceSpan, JobPipelineResult, RawJobRecord
from app.job_pipeline.evidence import validate_evidence
from app.job_pipeline.normalizers import (
    normalize_education,
    normalize_employment_type,
    normalize_experience,
    normalize_location,
    normalize_role_family,
    normalize_salary,
    normalize_skills,
    normalize_title,
)
from app.job_pipeline.quality import evaluate_quality
from app.job_pipeline.sections import parse_sections


class JobETLPipeline:
    """Rules-first ETL. LLM extraction can consume this contract later, never replace evidence."""

    parser_version = "JOB_ETL_V1"

    def process(self, record: RawJobRecord) -> JobPipelineResult:
        cleaned = clean_job_text(record.description_html)
        sections = parse_sections(cleaned.text)
        title = normalize_title(record.raw_title)
        location = normalize_location(record.raw_location)
        salary = normalize_salary(
            record.raw_salary or str(record.raw_payload.get("salary_text") or "")
        )
        company = str(
            record.company_name
            or record.raw_payload.get("company_name")
            or record.raw_payload.get("company")
            or ""
        ).strip()
        employment = normalize_employment_type(
            str(record.employment_type or record.raw_payload.get("job_type") or "")
        )
        education = normalize_education(
            str(
                record.education
                or record.raw_payload.get("education")
                or record.raw_payload.get("education_requirement")
                or ""
            )
        )
        experience = normalize_experience(
            str(
                record.experience
                or record.raw_payload.get("experience")
                or record.raw_payload.get("experience_requirement")
                or ""
            )
        )
        responsibilities = [item.text for item in sections.get("responsibilities", [])]
        requirements = [item.text for item in sections.get("requirements", [])]
        preferred = [item.text for item in sections.get("preferred", [])]
        benefits = [item.text for item in sections.get("benefits", [])]
        skills = normalize_skills("\n".join((*requirements, *preferred, cleaned.text)))
        evidence: list[EvidenceSpan] = []
        for index, skill in enumerate(skills):
            matched = validate_evidence(
                skill["matched_text"],
                cleaned.text,
                section="requirements",
                item_index=index,
            )
            evidence.append(
                EvidenceSpan(
                    value=skill["name"],
                    evidence_text=matched.evidence_text,
                    section=matched.section,
                    item_index=matched.item_index,
                    start_char=matched.start_char,
                    end_char=matched.end_char,
                    confidence=matched.confidence,
                    valid=matched.valid,
                )
            )
        quality = evaluate_quality(
            title=title,
            description=cleaned.text,
            company=company,
            location=location["normalized"],
            salary=salary,
            education=education,
            experience=experience,
            responsibilities=responsibilities,
            requirements=requirements,
            skills=skills,
            valid_evidence=sum(item.valid for item in evidence),
            evidence_count=len(evidence),
        )
        content_source = "\n".join((title, cleaned.text, str(salary), education, experience))
        content_hash = hashlib.sha256(content_source.encode("utf-8")).hexdigest()
        canonical = {
            "source": record.source,
            "source_job_id": record.source_job_id,
            "source_url": record.source_url,
            "title": title,
            "role_family": normalize_role_family(title, cleaned.text),
            "company": company,
            "location": location,
            "salary": salary,
            "education": education,
            "experience": experience,
            "employment_type": employment,
            "responsibilities": responsibilities,
            "requirements": requirements,
            "preferred_requirements": preferred,
            "benefits": benefits,
            "skills": skills,
            "clean_description": cleaned.text,
            "sections": {key: [item.text for item in values] for key, values in sections.items()},
            "evidence": [item.__dict__ for item in evidence if item.valid],
            "quality": {"score": quality.score, "level": quality.level, "details": quality.details},
            "content_hash": content_hash,
            "parser_version": self.parser_version,
            "first_seen_at": (record.collected_at or datetime.now(UTC)).isoformat(),
            "last_seen_at": (record.collected_at or datetime.now(UTC)).isoformat(),
            "lifecycle_status": "active",
        }
        warnings = (
            *cleaned.warnings,
            *(
                "missing_" + key
                for key, value in {
                    "company": company,
                    "location": location["normalized"],
                    "requirements": requirements,
                }.items()
                if not value
            ),
        )
        return JobPipelineResult(
            status="accepted" if quality.level != "low" else "accepted_with_warnings",
            canonical=canonical,
            quality_score=quality.score,
            quality_level=quality.level,
            warnings=tuple(dict.fromkeys(warnings)),
            stage_metrics={
                "cleaned_chars": len(cleaned.text),
                "sections": len(sections),
                "skills": len(skills),
                "evidence": len(evidence),
            },
            evidence=tuple(evidence),
        )
