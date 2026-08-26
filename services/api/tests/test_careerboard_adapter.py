from uuid import UUID

import pytest
from httpx import AsyncClient

from app.platforms.base import (
    CaptchaRequiredError,
    LoginRequiredError,
    RiskControlDetectedError,
    UnknownStateError,
)
from app.platforms.careerboard.actions import build_application_actions
from app.platforms.careerboard.detectors import CareerBoardPageState, PageSnapshot, detector
from app.platforms.careerboard.parser import parse_job_detail
from tests.test_campaigns import _upload_campaign_resume


def test_careerboard_parser_and_actions_are_independent() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000009")
    job = parse_job_detail(
        """
        <article data-cp-page="job-detail">
          <h1 data-cp-field="job-title">AI Agent Engineer</h1>
          <p data-cp-field="location">Remote</p>
          <div data-cp-field="description">Build safe browser agents.</div>
        </article>
        """,
        job_id=job_id,
    )
    assert job.id == job_id
    assert job.title == "AI Agent Engineer"
    assert job.location == "Remote"
    actions = build_application_actions(job_id=job_id, base_url="http://localhost:3000")
    assert actions[0].url == f"http://localhost:3000/mock-platform/jobs/{job_id}?task={{task_id}}"
    assert actions[2].target is not None
    assert actions[2].target.selector == "[data-cp-action='apply']"


@pytest.mark.parametrize(
    ("snapshot", "error"),
    [
        (PageSnapshot(html='<div data-cp-state="captcha">captcha</div>'), CaptchaRequiredError),
        (PageSnapshot(text="请先登录后继续"), LoginRequiredError),
        (PageSnapshot(text="安全验证：操作频繁"), RiskControlDetectedError),
        (PageSnapshot(html="<main data-page='unexpected'>changed</main>"), UnknownStateError),
    ],
)
def test_careerboard_detector_pauses_unsafe_states(
    snapshot: PageSnapshot, error: type[Exception]
) -> None:
    with pytest.raises(error):
        detector.detect(snapshot)


def test_careerboard_detector_accepts_expected_dom() -> None:
    state = detector.detect(
        PageSnapshot(
            html=(
                '<article data-cp-page="job-detail">'
                '<h1 data-cp-field="job-title">AI Agent Engineer</h1>'
                "</article>"
            )
        )
    )
    assert state == CareerBoardPageState.READY


async def _create_queued_careerboard_application(client: AsyncClient) -> str:
    resume_id = await _upload_campaign_resume(client)
    imported = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": (
                "CareerBoard Phase 9 Engineer\n\nLocation: Remote\n\n"
                "Responsibilities\n- Build safe browser adapters.\n\n"
                "Requirements\n- Python, FastAPI, and browser automation."
            ),
            "platform": "careerboard",
            "external_job_id": "phase9-careerboard-1",
        },
    )
    assert imported.status_code == 201
    job_id = imported.json()["items"][0]["job"]["id"]
    created = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "Phase 9 CareerBoard Campaign",
            "resume_id": resume_id,
            "job_ids": [job_id],
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    approved = await client.post(
        f"/api/campaigns/{campaign_id}/approve", json={"job_ids": [job_id]}
    )
    assert approved.status_code == 200
    return approved.json()["candidate_jobs"][0]["application"]["id"]


async def test_careerboard_browser_task_recovers_from_unknown_state(
    client: AsyncClient,
) -> None:
    application_id = await _create_queued_careerboard_application(client)
    catalog = await client.get("/api/browser-tasks/platforms")
    assert catalog.status_code == 200
    careerboard = next(item for item in catalog.json() if item["name"] == "careerboard")
    assert careerboard["safe_for_automation"] is False

    created = await client.post(
        "/api/browser-tasks",
        json={
            "application_id": application_id,
            "platform": "careerboard",
            "scenario": "UNKNOWN_STATE",
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert "data-cp-action='apply'" in created.json()["payload"]["actions"][2]["target"]["selector"]

    paused = await client.post(f"/api/browser-tasks/{task_id}/mock-extension")
    assert paused.status_code == 200
    assert paused.json()["status"] == "WAITING_FOR_USER"
    assert "DOM/state changed" in paused.json()["failure_reason"]

    applications = await client.get("/api/applications")
    application = next(
        item for item in applications.json()["items"] if item["id"] == application_id
    )
    assert application["status"] == "UNKNOWN_STATE"

    resumed = await client.post(
        f"/api/browser-tasks/{task_id}/resume",
        json={"decision": "resolved", "note": "用户确认页面已恢复"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RUNNING"
    completed = await client.post(f"/api/browser-tasks/{task_id}/mock-extension")
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
