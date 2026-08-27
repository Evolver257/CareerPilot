from httpx import AsyncClient


async def _upload_resume(client: AsyncClient) -> str:
    response = await client.post(
        "/api/resumes",
        files={
            "file": (
                "quick-score-resume.txt",
                b"""Alex Chen

Summary
Python backend engineer with FastAPI, RAG, LLM and PostgreSQL experience.

Experience
Acme - Backend Engineer | 2020 - 2025
- Built production APIs and retrieval services.

Skills
Python, FastAPI, RAG, LLM, PostgreSQL

Education
Bachelor's degree in Computer Science
""",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_job(client: AsyncClient, external_id: str, requirements: str) -> str:
    response = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": (
                "AI Agent Engineer\n\nLocation: Remote\n\n"
                "Responsibilities\n- Build retrieval services.\n\n"
                f"Requirements\n- {requirements}."
            ),
            "platform": "quick-score-test",
            "external_job_id": external_id,
        },
    )
    assert response.status_code == 201
    return response.json()["items"][0]["job"]["id"]


async def test_quick_score_is_deterministic_cached_and_does_not_call_llm(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    strong_job_id = await _import_job(
        client,
        "quick-strong",
        "Python, FastAPI, RAG, LLM, PostgreSQL, Bachelor's degree",
    )
    weak_job_id = await _import_job(
        client,
        "quick-weak",
        "Kotlin, Android, Firebase, Master's degree",
    )

    first = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [strong_job_id, weak_job_id]},
    )
    assert first.status_code == 200
    items = {item["job_id"]: item for item in first.json()["items"]}
    assert items[strong_job_id]["score"] > items[weak_job_id]["score"]
    assert items[strong_job_id]["cached"] is False
    assert items[weak_job_id]["cached"] is False

    repeated = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [strong_job_id, weak_job_id]},
    )
    assert repeated.status_code == 200
    repeated_items = {item["job_id"]: item for item in repeated.json()["items"]}
    assert repeated_items[strong_job_id]["cached"] is True
    assert repeated_items[weak_job_id]["cached"] is True
