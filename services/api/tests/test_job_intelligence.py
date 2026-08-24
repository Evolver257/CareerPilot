from httpx import AsyncClient

from app.services.job_intelligence import JobNormalizer


def test_job_normalizer_extracts_structured_job_skills_and_requirements() -> None:
    raw_jd = """Senior Backend Engineer

Location: Remote

Responsibilities
- Build FastAPI services for a global product.
- Improve PostgreSQL reliability and observability.

Requirements
- Bachelor's degree in Computer Science.
- 5+ years of backend experience.
- Python, FastAPI, PostgreSQL, and Docker.

Preferred Qualifications
- Experience with RAG and LLM applications.
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert analysis.structured_job.title == "Senior Backend Engineer"
    assert analysis.structured_job.role_category == "Backend Engineering"
    assert "Python" in analysis.structured_job.required_skills
    assert "RAG" in analysis.structured_job.preferred_skills
    assert "Bachelor's degree in Computer Science." in analysis.requirements.education
    assert "5+ years of backend experience." in analysis.requirements.experience
    assert len(analysis.requirements.responsibilities) == 2


async def test_import_and_analyze_job_endpoints(client: AsyncClient) -> None:
    raw_jd = """AI Platform Engineer

Requirements
- 3+ years of experience with Python and FastAPI.
- PostgreSQL and Docker required.

Responsibilities
- Build RAG services for job seekers.
"""
    imported = await client.post(
        "/api/jobs/import",
        json={"raw_jd": raw_jd, "platform": "manual", "external_job_id": "jd-001"},
    )

    assert imported.status_code == 201
    payload = imported.json()
    assert payload["created"] == 1
    assert payload["duplicates"] == 0
    assert payload["items"][0]["structured_job"]["title"] == "AI Platform Engineer"
    assert "Python" in payload["items"][0]["structured_job"]["required_skills"]
    assert payload["items"][0]["requirements"]["responsibilities"]
    assert payload["items"][0]["skills"]

    duplicate = await client.post(
        "/api/jobs/import",
        json={"raw_jd": raw_jd, "platform": "manual", "external_job_id": "jd-001"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] == 0
    assert duplicate.json()["duplicates"] == 1

    job_id = payload["items"][0]["job"]["id"]
    analyzed = await client.post(f"/api/jobs/{job_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["structured_job"]["role_category"] == "Backend Engineering"


async def test_mock_jobs_import_provides_dozens_of_deduplicated_jobs(client: AsyncClient) -> None:
    imported = await client.post("/api/jobs/import", json={"mode": "mock", "limit": 30})

    assert imported.status_code == 201
    payload = imported.json()
    assert payload["created"] == 30
    assert payload["total"] == 30
    assert all(item["job"]["platform"] == "mock" for item in payload["items"])
    assert all(item["skills"] for item in payload["items"])

    repeated = await client.post("/api/jobs/import", json={"mode": "mock", "limit": 30})
    assert repeated.status_code == 201
    assert repeated.json()["created"] == 0
    assert repeated.json()["duplicates"] == 30
