from httpx import AsyncClient

from tests.test_campaigns import _upload_campaign_resume


async def _create_queued_applications(client: AsyncClient) -> list[str]:
    resume_id = await _upload_campaign_resume(client)
    job_ids: list[str] = []
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
        job_ids.append(imported.json()["items"][0]["job"]["id"])
    created = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "Phase 8 Mock Browser Campaign",
            "resume_id": resume_id,
            "job_ids": job_ids,
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
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


async def test_manual_application_result_completes_task_and_marks_application(
    client: AsyncClient,
) -> None:
    application_ids = await _create_queued_applications(client)
    created = await client.post(
        "/api/browser-tasks",
        json={
            "application_id": application_ids[0],
            "platform": "mock",
            "scenario": "MANUAL_REQUIRED",
            "auto_start": False,
        },
    )
    assert created.status_code == 201

    completed = await client.post(
        f"/api/browser-tasks/{created.json()['id']}/mock-extension"
    )
    assert completed.status_code == 200
    task = completed.json()
    assert task["status"] == "COMPLETED"
    assert task["result"]["status"] == "MANUAL_REQUIRED"

    applications = await client.get("/api/applications")
    manual = next(
        item for item in applications.json()["items"] if item["id"] == application_ids[0]
    )
    assert manual["status"] == "MANUAL_REQUIRED"
    assert "立即网申" in (manual["failure_reason"] or "")


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


async def test_campaign_browser_tasks_exclude_stale_jobs_at_execution_boundary(
    client: AsyncClient,
    monkeypatch,
) -> None:
    application_ids = await _create_queued_applications(client)
    applications = await client.get("/api/applications")
    campaign_id = next(
        item["campaign_id"]
        for item in applications.json()["items"]
        if item["id"] == application_ids[0]
    )
    monkeypatch.setattr(
        "app.services.browser_tasks.is_fresh_for_auto_delivery",
        lambda *args, **kwargs: False,
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
    assert batch["created_count"] == 0
    assert batch["failed_count"] == 2
    assert {item["application_id"] for item in batch["failures"]} == set(application_ids)
    assert all("重新检索" in item["reason"] for item in batch["failures"])


async def test_pending_browser_task_rechecks_freshness_before_start(
    client: AsyncClient,
    monkeypatch,
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

    monkeypatch.setattr(
        "app.services.browser_tasks.is_fresh_for_auto_delivery",
        lambda *args, **kwargs: False,
    )
    started = await client.post(f"/api/browser-tasks/{created.json()['id']}/start")

    assert started.status_code == 409
    assert "重新检索" in started.json()["detail"]


async def test_campaign_task_records_are_grouped_cancelled_and_deleted_as_one_unit(
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
        json={"campaign_id": campaign_id, "auto_start": False},
    )
    assert created.status_code == 201

    records = await client.get("/api/browser-tasks/campaigns")
    assert records.status_code == 200
    record = next(
        item for item in records.json()["items"] if item["campaign_id"] == campaign_id
    )
    assert record["task_count"] == 2
    assert len(record["items"]) == 2
    assert {item["job_title"] for item in record["items"]} == {
        "Browser Phase 8 Engineer 1",
        "Browser Phase 8 Engineer 2",
    }

    active_delete = await client.delete(f"/api/browser-tasks/campaigns/{campaign_id}")
    assert active_delete.status_code == 409

    cancelled = await client.post(
        f"/api/browser-tasks/campaigns/{campaign_id}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancelled_count"] == 2

    deleted = await client.delete(f"/api/browser-tasks/campaigns/{campaign_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/browser-tasks/campaigns/{campaign_id}")
    assert missing.status_code == 404


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
