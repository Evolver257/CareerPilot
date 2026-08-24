from httpx import AsyncClient


async def test_health_returns_dependency_report(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "careerpilot-api"
    assert payload["dependencies"]["database"] == "ok"


async def test_job_create_list_get_and_duplicate_protection(client: AsyncClient) -> None:
    job_payload = {
        "platform": "mock",
        "external_job_id": "mock-001",
        "title": "AI Agent Intern",
        "description": "Build LLM and RAG systems",
        "location": "Shanghai",
        "job_type": "internship",
    }

    created = await client.post("/api/jobs", json=job_payload)
    assert created.status_code == 201
    job_id = created.json()["id"]

    listed = await client.get("/api/jobs", params={"search": "Agent"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == job_id

    fetched = await client.get(f"/api/jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "AI Agent Intern"

    duplicate = await client.post("/api/jobs", json=job_payload)
    assert duplicate.status_code == 409


async def test_missing_job_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
