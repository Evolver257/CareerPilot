from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.database import get_db
from app.main import app
from app.platforms.base import UnknownStateError
from app.platforms.zhaopin.adapter import ZhaopinAdapter, detail_id
from app.schemas.browser import BrowserActionResult, BrowserTaskResumeRequest
from app.services.browser_tasks import BrowserTaskService, browser_socket_manager
from tests.test_campaigns import _upload_campaign_resume

SOURCE = "https://www.zhaopin.com/jobdetail/CC123J456.htm"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        "http://www.zhaopin.com/jobdetail/CC123.htm",
        "https://www.zhaopin.com/sou?kw=AI",
        "https://www.zhaopin.com.evil.test/jobdetail/CC123.htm",
        "https://user@www.zhaopin.com/jobdetail/CC123.htm",
    ],
)
def test_detail_url_rejects_invalid_sources(value):
    assert detail_id(value) is None


@pytest.mark.parametrize(
    "status,proof,url,success",
    [
        ("submitted", None, SOURCE, True),
        ("clicked", "applied_button", SOURCE, True),
        ("submitted", "applied_button", SOURCE.replace("CC123J456", "OTHER"), True),
        ("submitted", "applied_button", SOURCE, False),
    ],
)
async def test_adapter_does_not_accept_click_only_wrong_job_or_failed_result(
    status, proof, url, success
):
    adapter = ZhaopinAdapter(None)
    adapter.repository = SimpleNamespace(
        get_application=AsyncMock(
            return_value=SimpleNamespace(
                platform="zhaopin", job=SimpleNamespace(external_job_id="CC123J456")
            )
        )
    )
    with pytest.raises(UnknownStateError):
        await adapter.submit_application(
            application_id=uuid4(),
            scenario="SUCCESS",
            observations={
                "click": {
                    "success": success,
                    "page_state": "READY",
                    "data": {
                        "zhaopin_action": "immediate_apply",
                        "application_status": status,
                        "confirmation": proof,
                        "page_url": url,
                    },
                }
            },
        )


async def queued_campaign(client):
    resume_id = await _upload_campaign_resume(client)
    imported = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": "AI Engineer\nLocation: 北京\nRequirements: Python RAG",
            "platform": "zhaopin",
            "external_job_id": "CC123J456",
            "source_url": SOURCE,
        },
    )
    assert imported.status_code == 201
    job_id = imported.json()["items"][0]["job"]["id"]
    created = await client.post(
        "/api/campaigns/curated",
        json={"name": "智联投递回归", "resume_id": resume_id, "job_ids": [job_id]},
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    approved = await client.post(
        f"/api/campaigns/{campaign_id}/approve", json={"job_ids": [job_id]}
    )
    assert approved.status_code == 200
    return campaign_id


@pytest.mark.parametrize("outcome", ["submitted", "already_applied", "uncertain", "CAPTCHA"])
@pytest.mark.parametrize("resume_after_pause", [False, True])
async def test_campaign_delivery_lifecycle_persists_confirmation_and_pauses(
    client, outcome, resume_after_pause
):
    campaign_id = await queued_campaign(client)
    request = {"campaign_id": campaign_id, "platform": "zhaopin", "auto_start": False}
    response = await client.post("/api/browser-tasks/campaign", json=request)
    assert response.status_code == 201
    batch = response.json()
    assert batch["created_count"] == 1 and batch["failed_count"] == 0
    repeated = await client.post("/api/browser-tasks/campaign", json=request)
    assert repeated.json()["created_count"] == 0 and repeated.json()["reused_count"] == 1
    task = batch["items"][0]
    assert task["status"] == "PENDING"
    assert f"task={task['id']}" in task["payload"]["actions"][0]["url"]
    assert task["payload"]["actions"][2]["target"]["name"] == "立即投递"
    task_id = UUID(task["id"])
    socket = SimpleNamespace(send_json=AsyncMock())
    # Isolated in-memory database + fake socket, never a real browser submission.
    async for session in app.dependency_overrides[get_db]():
        from app.llm.provider import MockLLMProvider

        service = BrowserTaskService(session, MockLLMProvider())
        try:
            current = await service.connect_extension(task_id, socket, None)
            for _ in range(4):
                action = current.current_action
                is_click = action["action"] == "CLICK"
                success = not (is_click and outcome in {"uncertain", "CAPTCHA"})
                current = await service.handle_action_result(
                    task_id,
                    BrowserActionResult(
                        action_id=action["id"],
                        success=success,
                        page_state=("CAPTCHA" if outcome == "CAPTCHA" else "UNKNOWN_STATE")
                        if not success
                        else "READY",
                        data={
                            "zhaopin_action": "immediate_apply" if is_click else "inspect",
                            "application_status": outcome if is_click else "ready",
                            "page_url": SOURCE,
                            "confirmation": "applied_button" if success and is_click else None,
                        },
                    ),
                )
                if current.status == "WAITING_FOR_USER":
                    assert current.payload["observations"][action["id"]]["success"] is False
                    break
            assert current.status == (
                "COMPLETED" if outcome in {"submitted", "already_applied"} else "WAITING_FOR_USER"
            )
            if resume_after_pause and current.status == "WAITING_FOR_USER":
                current = await service.resume(
                    task_id, BrowserTaskResumeRequest(decision="resolved")
                )
                assert current.current_action["action"] == "CLICK"
                for _ in range(2):
                    current = await service.handle_action_result(
                        task_id,
                        BrowserActionResult(
                            action_id=current.current_action["id"],
                            page_state="READY",
                            data={
                                "zhaopin_action": "immediate_apply"
                                if current.current_action["action"] == "CLICK"
                                else "inspect",
                                "application_status": "already_applied",
                                "confirmation": "applied_button",
                                "page_url": SOURCE,
                            },
                        ),
                    )
                assert current.status == "COMPLETED"
        finally:
            browser_socket_manager.disconnect(task_id, socket)
    applications = (await client.get("/api/applications")).json()["items"]
    application = next(item for item in applications if item["campaign_id"] == campaign_id)
    assert (application["status"] == "SUBMITTED") == (
        outcome in {"submitted", "already_applied"} or resume_after_pause
    )
