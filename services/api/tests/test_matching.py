from httpx import AsyncClient


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
