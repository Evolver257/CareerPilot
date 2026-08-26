from httpx import AsyncClient


async def _upload_resume(client: AsyncClient, name: str = "Maintenance Resume") -> str:
    text = """Alex Chen

Summary
Backend Engineer with Python and FastAPI experience.

Skills
Python, FastAPI, PostgreSQL
"""
    response = await client.post(
        "/api/resumes",
        files={"file": (f"{name}.txt", text.encode(), "text/plain")},
        data={"name": name},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_job(client: AsyncClient, external_id: str = "crud-job") -> str:
    response = await client.post(
        "/api/jobs",
        json={
            "platform": "maintenance-test",
            "external_job_id": external_id,
            "title": "Backend Engineer",
            "description": "Python backend role.",
            "location": "Remote",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_job_update_delete_and_reference_protection(client: AsyncClient) -> None:
    job_id = await _create_job(client)
    updated = await client.patch(
        f"/api/jobs/{job_id}",
        json={
            "title": "Senior Backend Engineer",
            "description": "Requirements\n- Python, FastAPI, PostgreSQL, and Docker.",
            "salary_min": 20,
            "salary_max": 30,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Senior Backend Engineer"
    assert updated.json()["salary_min"] == 20

    deleted = await client.delete(f"/api/jobs/{job_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/jobs/{job_id}")).status_code == 404

    resume_id = await _upload_resume(client)
    protected_job_id = await _create_job(client, "protected-job")
    curated = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "Protected Campaign",
            "resume_id": resume_id,
            "job_ids": [protected_job_id],
        },
    )
    assert curated.status_code == 201
    assert (await client.delete(f"/api/jobs/{protected_job_id}")).status_code == 409


async def test_resume_update_default_delete_and_reference_protection(
    client: AsyncClient,
) -> None:
    first_id = await _upload_resume(client, "First Resume")
    second_id = await _upload_resume(client, "Second Resume")
    updated = await client.patch(
        f"/api/resumes/{second_id}",
        json={
            "name": "AI Resume",
            "is_default": True,
            "raw_text": "Summary\nAI Engineer\nSkills\nPython, RAG, FastAPI",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "AI Resume"
    assert updated.json()["is_default"] is True
    assert updated.json()["version"] == 2
    assert "RAG" in updated.json()["structured_profile"]["skills"]

    assert (await client.delete(f"/api/resumes/{first_id}")).status_code == 204
    job_id = await _create_job(client, "resume-protected-job")
    curated = await client.post(
        "/api/campaigns/curated",
        json={"name": "Uses Resume", "resume_id": second_id, "job_ids": [job_id]},
    )
    assert curated.status_code == 201
    assert (await client.delete(f"/api/resumes/{second_id}")).status_code == 409


async def test_draft_campaign_can_be_updated_and_terminal_campaign_deleted(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    created = await client.post(
        "/api/campaigns",
        json={"name": "Draft", "resume_id": resume_id},
    )
    campaign_id = created.json()["id"]
    updated = await client.patch(
        f"/api/campaigns/{campaign_id}",
        json={
            "name": "Updated Draft",
            "keywords": ["Agent", "RAG", "Agent"],
            "target_cities": ["北京"],
            "min_score": 75,
            "max_jobs": 8,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Draft"
    assert updated.json()["filters"]["keywords"] == ["Agent", "RAG"]
    assert updated.json()["target_cities"] == ["北京"]
    assert (await client.delete(f"/api/campaigns/{campaign_id}")).status_code == 204

    job_id = await _create_job(client, "active-campaign-job")
    active = await client.post(
        "/api/campaigns/curated",
        json={"name": "Active", "resume_id": resume_id, "job_ids": [job_id]},
    )
    active_id = active.json()["id"]
    assert (await client.delete(f"/api/campaigns/{active_id}")).status_code == 409
    assert (await client.post(f"/api/campaigns/{active_id}/cancel")).status_code == 200
    assert (await client.delete(f"/api/campaigns/{active_id}")).status_code == 204


async def test_pending_agent_run_can_be_updated_and_cancelled_run_deleted(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    created = await client.post(
        "/api/agent-runs",
        json={
            "goal": "Find Python jobs",
            "resume_id": resume_id,
            "auto_start": False,
        },
    )
    run_id = created.json()["id"]
    updated = await client.patch(
        f"/api/agent-runs/{run_id}",
        json={"goal": "Find RAG jobs in 北京", "max_steps": 18},
    )
    assert updated.status_code == 200
    assert updated.json()["input"]["goal"] == "Find RAG jobs in 北京"
    assert updated.json()["max_steps"] == 18

    paused = await client.post(f"/api/agent-runs/{run_id}/pause")
    assert paused.status_code == 200
    assert (await client.delete(f"/api/agent-runs/{run_id}")).status_code == 409
    assert (await client.post(f"/api/agent-runs/{run_id}/cancel")).status_code == 200
    assert (await client.delete(f"/api/agent-runs/{run_id}")).status_code == 204
