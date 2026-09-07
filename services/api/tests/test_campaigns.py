from httpx import AsyncClient


async def test_curated_selection_is_reused_without_approving_or_reordering(client: AsyncClient):
    resume_id = await _upload_campaign_resume(client)
    job_ids = await _import_campaign_jobs(client)
    payload = {"name": "Selected jobs", "resume_id": resume_id, "job_ids": job_ids[:2]}
    first = await client.post("/api/campaigns/curated", json=payload)
    repeated = await client.post(
        "/api/campaigns/curated", json={**payload, "job_ids": job_ids[1::-1]}
    )
    assert first.status_code == repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["reused_existing"] is True
    assert repeated.json()["status"] == "WAITING_APPROVAL"
    assert (await client.get("/api/applications")).json()["total"] == 2
    different = await client.post(
        "/api/campaigns/curated", json={**payload, "job_ids": job_ids[1:3]}
    )
    assert different.json()["id"] != first.json()["id"]
    await client.post(f"/api/campaigns/{first.json()['id']}/cancel")
    new = await client.post("/api/campaigns/curated", json=payload)
    assert new.json()["id"] != first.json()["id"]


async def test_plan_completes_only_after_every_application_is_terminal(client: AsyncClient):
    resume_id = await _upload_campaign_resume(client)
    job_ids = (await _import_campaign_jobs(client))[:2]
    plan = (
        await client.post(
            "/api/campaigns/curated",
            json={
                "name": "Completion",
                "resume_id": resume_id,
                "job_ids": job_ids,
            },
        )
    ).json()
    cid = plan["id"]
    await client.post(f"/api/campaigns/{cid}/approve", json={"job_ids": job_ids})
    first, second = [item["application"]["id"] for item in plan["candidate_jobs"]]
    for action in ["execute", "captcha_required"]:
        response = await client.post(
            f"/api/applications/{first}/transition", json={"action": action}
        )
        assert response.status_code == 200, response.text
    await client.post(f"/api/applications/{second}/transition", json={"action": "cancel"})
    assert (await client.get(f"/api/campaigns/{cid}")).json()["status"] == "RUNNING"
    for action in ["retry", "submit"]:
        response = await client.post(
            f"/api/applications/{first}/transition", json={"action": action}
        )
        assert response.status_code == 200, response.text
    completed = (await client.get(f"/api/campaigns/{cid}")).json()
    assert completed["status"] == "COMPLETED"
    assert completed["finished_at"] is not None
    assert {item["application"]["status"] for item in completed["candidate_jobs"]} == {
        "SUBMITTED",
        "CANCELLED",
    }


async def test_all_rejected_plan_is_cancelled_and_applications_are_paginated(client: AsyncClient):
    resume_id = await _upload_campaign_resume(client)
    job_ids = (await _import_campaign_jobs(client))[:3]
    plan = (
        await client.post(
            "/api/campaigns/curated",
            json={
                "name": "Reject all",
                "resume_id": resume_id,
                "job_ids": job_ids,
            },
        )
    ).json()
    rejected = await client.post(f"/api/campaigns/{plan['id']}/reject", json={"job_ids": job_ids})
    assert rejected.json()["status"] == "CANCELLED"
    first = (await client.get("/api/applications", params={"page": 1, "page_size": 2})).json()
    second = (await client.get("/api/applications", params={"page": 2, "page_size": 2})).json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]}
    filtered = (
        await client.get(
            "/api/applications", params={"statuses": "QUEUED", "campaign_id": plan["id"]}
        )
    ).json()
    assert filtered["total"] == 0
    assert filtered["status_counts"] == {"CANCELLED": 3}
    assert (await client.get("/api/applications?page=0")).status_code == 422
    assert (await client.get("/api/applications?page_size=201")).status_code == 422


async def test_campaign_http_accepts_200_and_rejects_201(client: AsyncClient) -> None:
    resume_id = await _upload_campaign_resume(client)
    created = await client.post(
        "/api/campaigns",
        json={
            "name": "200-job plan",
            "resume_id": resume_id,
            "max_jobs": 200,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["max_jobs"] == 200
    campaign_id = created.json()["id"]
    updated = await client.patch(f"/api/campaigns/{campaign_id}", json={"max_jobs": 200})
    assert updated.status_code == 200, updated.text
    rejected = await client.patch(f"/api/campaigns/{campaign_id}", json={"max_jobs": 201})
    assert rejected.status_code == 422


async def _upload_campaign_resume(client: AsyncClient) -> str:
    resume_text = """Alex Chen

Summary
Backend Engineer with 5 years of Python, FastAPI, PostgreSQL, Redis, Docker, RAG, and LLM.

Experience
Acme - Backend Engineer | 2020 - 2025
- Built production APIs and semantic retrieval services.

Skills
Python, FastAPI, PostgreSQL, Redis, Docker, RAG, LLM

Education
Bachelor's degree in Computer Science
"""
    response = await client.post(
        "/api/resumes",
        files={"file": ("campaign-resume.txt", resume_text.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_campaign_jobs(client: AsyncClient) -> list[str]:
    skills = [
        "Python, FastAPI, PostgreSQL, and Docker",
        "Python, RAG, LLM, and vector search",
        "Python, SQL, ETL, and PostgreSQL",
        "Python, Redis, REST APIs, and Docker",
        "TypeScript, React, Next.js, and CSS",
        "Kotlin, Android, and Firebase",
    ]
    job_ids: list[str] = []
    for index, requirements in enumerate(skills, start=1):
        response = await client.post(
            "/api/jobs/import",
            json={
                "raw_jd": (
                    f"Campaign Engineer {index}\n\nLocation: Remote\n\n"
                    f"Responsibilities\n- Build system {index}.\n\nRequirements\n"
                    f"- Bachelor's degree.\n- 3+ years of experience.\n- {requirements}."
                ),
                "platform": "campaign-test",
                "external_job_id": f"campaign-{index:03d}",
            },
        )
        assert response.status_code == 201
        job_ids.append(response.json()["items"][0]["job"]["id"])
    return job_ids


async def test_campaign_full_flow_preserves_pause_resume_state(client: AsyncClient) -> None:
    resume_id = await _upload_campaign_resume(client)
    job_ids = await _import_campaign_jobs(client)

    created = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "AI Agent Internship",
            "resume_id": resume_id,
            "job_ids": job_ids[:4],
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    campaign = created.json()
    assert campaign["status"] == "WAITING_APPROVAL"
    assert campaign["candidate_count"] == 4
    assert campaign["waiting_approval_count"] == 4
    assert all(item["status"] == "WAITING_APPROVAL" for item in campaign["candidate_jobs"])
    assert all(
        [event["to"] for event in item["application"]["metadata"]["state_history"]]
        == ["DISCOVERED", "ANALYZED", "QUALIFIED", "WAITING_APPROVAL"]
        for item in campaign["candidate_jobs"]
    )

    approved_job_ids = [item["job_id"] for item in campaign["candidate_jobs"][:2]]
    approved = await client.post(
        f"/api/campaigns/{campaign_id}/approve",
        json={"job_ids": approved_job_ids},
    )
    assert approved.status_code == 200
    campaign = approved.json()
    assert campaign["status"] == "RUNNING"
    queued = [item for item in campaign["candidate_jobs"] if item["job_id"] in approved_job_ids]
    assert all(item["status"] == "QUEUED" for item in queued)
    assert all(item["application"]["status"] == "QUEUED" for item in queued)

    first_application_id = queued[0]["application"]["id"]
    executing = await client.post(
        f"/api/applications/{first_application_id}/transition",
        json={"action": "execute"},
    )
    assert executing.status_code == 200
    assert executing.json()["status"] == "EXECUTING"
    captcha = await client.post(
        f"/api/applications/{first_application_id}/transition",
        json={"action": "captcha_required", "reason": "Mock CAPTCHA"},
    )
    assert captcha.status_code == 200
    assert captcha.json()["status"] == "CAPTCHA_REQUIRED"
    retried = await client.post(
        f"/api/applications/{first_application_id}/transition",
        json={"action": "retry"},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "EXECUTING"

    paused = await client.post(f"/api/campaigns/{campaign_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    paused_apps = {
        item["job_id"]: item["application"]["status"]
        for item in paused.json()["candidate_jobs"]
        if item["job_id"] in approved_job_ids
    }
    assert set(paused_apps.values()) == {"PAUSED"}

    persisted = await client.get(f"/api/campaigns/{campaign_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "PAUSED"

    resumed = await client.post(f"/api/campaigns/{campaign_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RUNNING"
    resumed_apps = {
        item["job_id"]: item["application"]["status"]
        for item in resumed.json()["candidate_jobs"]
        if item["job_id"] in approved_job_ids
    }
    assert set(resumed_apps.values()) == {"EXECUTING", "QUEUED"}

    applications = await client.get("/api/applications")
    assert applications.status_code == 200
    assert applications.json()["total"] == 4

    cancelled = await client.post(f"/api/campaigns/{campaign_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert all(
        item["application"]["status"] == "CANCELLED" for item in cancelled.json()["candidate_jobs"]
    )


async def test_campaign_start_creates_cancelable_persisted_ranking_run(
    client: AsyncClient,
    monkeypatch,
) -> None:
    resume_id = await _upload_campaign_resume(client)
    await _import_campaign_jobs(client)
    scheduled: list[str] = []
    monkeypatch.setattr(
        "app.api.campaigns.schedule_ranking_run",
        lambda run_id: scheduled.append(str(run_id)),
    )
    created = await client.post(
        "/api/campaigns",
        json={
            "name": "Durable deep ranking",
            "resume_id": resume_id,
            "keywords": ["Campaign Engineer"],
            "min_score": 0,
            "max_jobs": 4,
            "scoring_mode": "llm",
        },
    )

    started = await client.post(f"/api/campaigns/{created.json()['id']}/start")

    assert started.status_code == 200
    campaign = started.json()
    assert campaign["status"] == "RANKING"
    assert campaign["scoring_mode"] == "llm"
    assert campaign["ranking_run"]["status"] == "PENDING"
    assert campaign["ranking_run"]["campaign_id"] == campaign["id"]
    assert scheduled == [campaign["ranking_run"]["id"]]

    cancelled = await client.post(f"/api/campaigns/{campaign['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["ranking_run"]["status"] == "CANCELLED"


async def test_campaign_can_reject_waiting_jobs_without_queuing_them(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_campaign_resume(client)
    job_ids = await _import_campaign_jobs(client)
    created = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "Selective campaign",
            "resume_id": resume_id,
            "job_ids": job_ids[:3],
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    rejected = await client.post(
        f"/api/campaigns/{campaign_id}/reject",
        json={"job_ids": [job_ids[1]]},
    )

    assert rejected.status_code == 200
    campaign = rejected.json()
    rejected_job = next(item for item in campaign["candidate_jobs"] if item["job_id"] == job_ids[1])
    assert rejected_job["status"] == "REJECTED"
    assert rejected_job["application"]["status"] == "CANCELLED"
    assert rejected_job["application"]["failure_reason"] == "用户从投递计划中剔除"
    assert campaign["waiting_approval_count"] == 2
    assert campaign["queued_count"] == 0

    persisted = await client.get(f"/api/campaigns/{campaign_id}")
    assert persisted.status_code == 200
    persisted_rejected = next(
        item for item in persisted.json()["candidate_jobs"] if item["job_id"] == job_ids[1]
    )
    assert persisted_rejected["status"] == "REJECTED"


async def test_campaign_requires_resume_and_rejects_invalid_transition(
    client: AsyncClient,
) -> None:
    without_resume = await client.post(
        "/api/campaigns",
        json={"name": "No Resume Campaign"},
    )
    assert without_resume.status_code == 409

    resume_id = await _upload_campaign_resume(client)
    created = await client.post(
        "/api/campaigns",
        json={"name": "Draft Campaign", "resume_id": resume_id},
    )
    campaign_id = created.json()["id"]
    invalid_resume = await client.post(f"/api/campaigns/{campaign_id}/resume")
    assert invalid_resume.status_code == 409
    assert "resume" in invalid_resume.json()["detail"].lower()
