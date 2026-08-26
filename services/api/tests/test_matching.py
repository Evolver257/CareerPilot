from httpx import AsyncClient

from app.api.dependencies import get_llm_provider
from app.llm.provider import LLMProviderError, MockLLMProvider
from app.main import app


class EmptyResponseProvider(MockLLMProvider):
    provider_name = "empty-test"
    model = "empty-test-model"

    async def generate_structured(self, prompt, schema, *, model=None):
        raise LLMProviderError("provider returned an empty response")


async def _upload_resume(client: AsyncClient) -> str:
    resume_text = """Alex Chen

Summary
Backend Engineer with 5 years of Python, FastAPI, PostgreSQL, RAG, and LLM experience.

Experience
Acme - Backend Engineer | 2020 - 2025
- Built reliable FastAPI services and PostgreSQL data pipelines.

Projects
CareerPilot RAG platform using Python, LLM, Docker, and semantic retrieval.

Skills
Python, FastAPI, PostgreSQL, Docker, Redis, RAG, LLM

Education
Bachelor's degree in Computer Science
"""
    response = await client.post(
        "/api/resumes",
        files={"file": ("matching-resume.txt", resume_text.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_job(client: AsyncClient, raw_jd: str, external_id: str) -> str:
    response = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": raw_jd,
            "platform": "matching-test",
            "external_job_id": external_id,
        },
    )
    assert response.status_code == 201
    return response.json()["items"][0]["job"]["id"]


async def test_same_resume_receives_different_scores_for_different_jobs(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    backend_job_id = await _import_job(
        client,
        """Senior Backend Engineer

Location: Remote

Responsibilities
- Build RAG and LLM services with FastAPI.
- Operate PostgreSQL and Docker workloads.

Requirements
- Bachelor's degree in Computer Science.
- 3+ years of backend experience.
- Python, FastAPI, PostgreSQL, Docker, RAG, and LLM.
""",
        "backend-001",
    )
    frontend_job_id = await _import_job(
        client,
        """Senior Frontend Engineer

Location: Remote

Responsibilities
- Build design systems and browser interfaces.

Requirements
- Bachelor's degree or equivalent experience.
- 3+ years of frontend experience.
- TypeScript, React, Next.js, CSS, and Figma.
""",
        "frontend-001",
    )

    backend = await client.post(
        f"/api/jobs/{backend_job_id}/score", json={"resume_id": resume_id}
    )
    frontend = await client.post(
        f"/api/jobs/{frontend_job_id}/score", json={"resume_id": resume_id}
    )

    assert backend.status_code == 200
    assert frontend.status_code == 200
    backend_score = backend.json()
    frontend_score = frontend.json()
    assert backend_score["final_score"] > frontend_score["final_score"] + 15
    assert backend_score["skill_score"] > frontend_score["skill_score"]
    assert "Python" in backend_score["matched_skills"]
    assert "React" in frontend_score["missing_skills"]
    assert backend_score["resume_evidence"]
    assert all("content" in evidence for evidence in backend_score["resume_evidence"])
    assert backend_score["recommendation"] in {"strong_apply", "apply", "maybe", "skip"}
    assert backend_score["reasoning_summary"]
    assert abs(sum(backend_score["weights"].values()) - 1.0) < 0.0001


async def test_scoring_requires_an_available_resume(client: AsyncClient) -> None:
    job_id = await _import_job(
        client,
        """Backend Engineer

Requirements
- Python and FastAPI.
""",
        "no-resume-001",
    )

    response = await client.post(f"/api/jobs/{job_id}/score")

    assert response.status_code == 409
    assert "resume" in response.json()["detail"].lower()


async def test_scoring_reuses_cache_until_forced_or_job_changes(client: AsyncClient) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_job(
        client,
        "Backend Engineer\nRequirements\n- Python and FastAPI.",
        "score-cache-001",
    )

    first = await client.post(
        f"/api/jobs/{job_id}/score", json={"resume_id": resume_id}
    )
    cached = await client.post(
        f"/api/jobs/{job_id}/score", json={"resume_id": resume_id}
    )
    forced = await client.post(
        f"/api/jobs/{job_id}/score",
        json={"resume_id": resume_id, "force": True},
    )

    assert first.json()["id"] == cached.json()["id"]
    assert forced.json()["id"] != cached.json()["id"]

    changed = await client.patch(
        f"/api/jobs/{job_id}", json={"location": "北京"}
    )
    assert changed.status_code == 200
    rescored = await client.post(
        f"/api/jobs/{job_id}/score", json={"resume_id": resume_id}
    )
    assert rescored.json()["id"] != forced.json()["id"]


async def test_skill_coverage_agrees_with_technologies_present_in_resume_text(
    client: AsyncClient,
) -> None:
    resume = await client.post(
        "/api/resumes",
        files={
            "file": (
                "narrative-resume.txt",
                "专业技能\n熟悉 Java，掌握 MySQL 与 PostgreSQL 数据库开发。".encode(),
                "text/plain",
            )
        },
    )
    job_id = await _import_job(
        client,
        "Backend Engineer\nRequirements\n- Java, SQL, MySQL and PostgreSQL.",
        "narrative-skills-001",
    )

    scored = await client.post(
        f"/api/jobs/{job_id}/score", json={"resume_id": resume.json()["id"]}
    )

    assert scored.status_code == 200
    result = scored.json()
    assert {"Java", "SQL", "MySQL", "PostgreSQL"}.issubset(result["matched_skills"])
    assert not {"SQL", "MySQL", "PostgreSQL"}.intersection(result["missing_skills"])


async def test_llm_empty_response_falls_back_without_failing_the_score(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_job(
        client,
        "Backend Engineer\nRequirements\n- Python, FastAPI and PostgreSQL.",
        "fallback-score-001",
    )
    provider = EmptyResponseProvider()

    async def override_provider():
        return provider

    app.dependency_overrides[get_llm_provider] = override_provider
    try:
        response = await client.post(
            f"/api/jobs/{job_id}/score",
            json={"resume_id": resume_id, "force": True},
        )
        retried = await client.post(f"/api/jobs/{job_id}/score", json={"resume_id": resume_id})
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)

    assert response.status_code == 200
    score = response.json()
    assert score["judge_source"] == "fallback"
    assert any("确定性评分降级" in risk for risk in score["risks"])
    assert retried.status_code == 200
    assert retried.json()["id"] != score["id"]
