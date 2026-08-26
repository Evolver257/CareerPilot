from httpx import AsyncClient

from tests.test_campaigns import _upload_campaign_resume


async def _create_queued_applications(client: AsyncClient) -> list[str]:
    resume_id = await _upload_campaign_resume(client)
    for index in range(1, 3):
        imported = await client.post(
            "/api/jobs/import",
            json={
                "raw_jd": (
                    f"Browser Phase 8 Engineer {index}\n\nLocation: Remote\n\n"
                    "Responsibilities\n- Submit applications on a mock platform.\n\n"
                    "Requirements\n- Python, FastAPI, and Browser Agent."
                ),
                "platform": "mock",
                "external_job_id": f"phase8-browser-{index}",
            },
        )
        assert imported.status_code == 201
    created = await client.post(
        "/api/campaigns",
        json={
            "name": "Phase 8 Mock Browser Campaign",
            "resume_id": resume_id,
            "keywords": ["Browser Phase 8"],
            "target_cities": ["Remote"],
            "min_score": 0,
            "max_jobs": 2,
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/campaigns/{campaign_id}/start")
    assert started.status_code == 200
    job_ids = [item["job_id"] for item in started.json()["candidate_jobs"]]
    approved = await client.post(
        f"/api/campaigns/{campaign_id}/approve", json={"job_ids": job_ids}
    )
    assert approved.status_code == 200
    return [
        item["application"]["id"]
        for item in approved.json()["candidate_jobs"]
        if item["application"] is not None
    ]


async def test_mock_browser_task_completes_application_and_records_actions(
    client: AsyncClient,
) -> None:
    application_ids = await _create_queued_applications(client)
    created = await client.post(
        "/api/browser-tasks",
        json={
            "application_id": application_ids[0],
            "platform": "mock",
            "scenario": "SUCCESS",
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "PENDING"
    assert len(task["payload"]["actions"]) == 4
    assert task["payload"]["actions"][0]["action"] == "NAVIGATE"
    assert f"task={task['id']}" in task["payload"]["actions"][0]["url"]

    executed = await client.post(f"/api/browser-tasks/{task['id']}/mock-extension")
    assert executed.status_code == 200
    completed = executed.json()
    assert completed["status"] == "COMPLETED"
    assert completed["result"]["status"] == "SUBMITTED"
    assert [event["event_type"] for event in completed["events"]].count(
        "BROWSER_ACTION_SENT"
    ) == 4

    applications = await client.get("/api/applications")
    submitted = next(
        item for item in applications.json()["items"] if item["id"] == application_ids[0]
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["applied_at"] is not None


async def test_campaign_browser_tasks_create_all_queued_applications_idempotently(
    client: AsyncClient,
) -> None:
    application_ids = await _create_queued_applications(client)
    applications = await client.get("/api/applications")
    campaign_id = next(
        item["campaign_id"]
        for item in applications.json()["items"]
        if item["id"] == application_ids[0]
    )

    created = await client.post(
        "/api/browser-tasks/campaign",
        json={
            "campaign_id": campaign_id,
            "scenario": "SUCCESS",
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    batch = created.json()
    assert batch["queued_count"] == 2
    assert batch["created_count"] == 2
    assert batch["reused_count"] == 0
    assert batch["failed_count"] == 0
    assert {item["application_id"] for item in batch["items"]} == set(application_ids)
    assert {item["status"] for item in batch["items"]} == {"PENDING"}

    repeated = await client.post(
        "/api/browser-tasks/campaign",
        json={
            "campaign_id": campaign_id,
            "scenario": "SUCCESS",
            "auto_start": False,
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["created_count"] == 0
    assert repeated.json()["reused_count"] == 2

    for task in batch["items"]:
        completed = await client.post(f"/api/browser-tasks/{task['id']}/mock-extension")
        assert completed.status_code == 200
        assert completed.json()["status"] == "COMPLETED"

    refreshed = await client.get("/api/applications")
    statuses = {
        item["id"]: item["status"]
        for item in refreshed.json()["items"]
        if item["id"] in application_ids
    }
    assert statuses == {application_id: "SUBMITTED" for application_id in application_ids}


async def test_mock_browser_task_pauses_on_captcha_and_resumes_after_user_action(
    client: AsyncClient,
) -> None:
    application_ids = await _create_queued_applications(client)
    created = await client.post(
        "/api/browser-tasks",
        json={
            "application_id": application_ids[1],
            "scenario": "CAPTCHA_REQUIRED",
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    paused = await client.post(f"/api/browser-tasks/{task_id}/mock-extension")
    assert paused.status_code == 200
    assert paused.json()["status"] == "WAITING_FOR_USER"
    assert paused.json()["failure_reason"] == "Mock platform CAPTCHA requires user action"

    applications = await client.get("/api/applications")
    captcha = next(
        item for item in applications.json()["items"] if item["id"] == application_ids[1]
    )
    assert captcha["status"] == "CAPTCHA_REQUIRED"

    resumed = await client.post(
        f"/api/browser-tasks/{task_id}/resume",
        json={"decision": "resolved", "note": "Mock CAPTCHA solved by user"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RUNNING"
    completed = await client.post(f"/api/browser-tasks/{task_id}/mock-extension")
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
