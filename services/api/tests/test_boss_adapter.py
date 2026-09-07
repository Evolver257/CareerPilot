from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    LoginRequiredError,
    PlatformLimitError,
    RiskControlDetectedError,
    UnknownStateError,
)
from app.platforms.boss.actions import build_application_actions
from app.platforms.boss.detectors import BossPageSnapshot, BossPageState, detector
from app.platforms.boss.parser import parse_job_list
from app.platforms.boss.text import decode_boss_salary
from tests.test_campaigns import _upload_campaign_resume


def test_boss_parser_extracts_visible_cards_and_actions_are_user_session_bound() -> None:
    jobs = parse_job_list(
        """
        <ul>
          <li class="job-card-wrapper" data-jobid="boss-001">
            <a class="job-card-left" href="https://www.zhipin.com/job_detail/boss-001.html">
              <span class="job-name">AI Agent 实习</span>
              <span class="company-name">CareerPilot Labs</span>
              <span class="job-area">北京</span>
              <span class="salary">5-8K</span>
              <div class="job-detail">参与 RAG 和 Browser Agent 开发</div>
            </a>
          </li>
        </ul>
        """,
        page_url="https://www.zhipin.com/zhaopin/",
    )
    assert jobs[0].external_job_id == "boss-001"
    assert jobs[0].title == "AI Agent 实习"
    assert jobs[0].company_name == "CareerPilot Labs"
    assert jobs[0].location == "北京"
    actions = build_application_actions(source_url=jobs[0].source_url)
    assert actions[0].url.endswith("task={task_id}")
    assert actions[2].metadata["requires_user_approval"] is True
    assert actions[2].metadata["mode"] == "boss_immediate_communication"
    assert actions[2].target is not None
    assert ".btn-startchat" in (actions[2].target.selector or "")


def test_boss_parser_supports_current_split_pane_job_cards() -> None:
    jobs = parse_job_list(
        """
        <div class="card-area">
          <div class="job-card-wrap active">
            <li class="job-card-box">
              <div class="job-info">
                <div class="job-title clearfix">
                  <a class="job-name" href="/job_detail/current-encrypted-id.html">
                    java开发实习生
                  </a>
                  <span class="job-salary">150-200元/天</span>
                </div>
                <ul class="tag-list"><li>5天/周</li><li>6个月</li><li>大专</li></ul>
              </div>
              <div class="job-card-footer">
                <a class="boss-info"><span class="boss-name">智乐活</span></a>
                <span class="company-location">北京·朝阳区·望京</span>
              </div>
            </li>
          </div>
        </div>
        """,
        page_url="https://www.zhipin.com/web/geek/jobs?query=AI&city=101010100",
    )
    assert len(jobs) == 1
    assert jobs[0].external_job_id == "current-encrypted-id"
    assert jobs[0].title == "java开发实习生"
    assert jobs[0].salary_text == "150-200元/天"
    assert jobs[0].company_name == "智乐活"
    assert jobs[0].location == "北京·朝阳区·望京"


def test_boss_private_font_salary_digits_are_decoded() -> None:
    assert decode_boss_salary("-元/天") == "150-200元/天"
    assert decode_boss_salary("-K") == "3-5K"


@pytest.mark.parametrize(
    ("snapshot", "error"),
    [
        (
            BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="验证码"),
            CaptchaRequiredError,
        ),
        (
            BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="请先登录"),
            LoginRequiredError,
        ),
        (
            BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="操作频繁"),
            PlatformLimitError,
        ),
        (
            BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="安全验证"),
            RiskControlDetectedError,
        ),
        (
            BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="页面不存在"),
            DomChangedError,
        ),
        (BossPageSnapshot(url="https://example.com/", text="职位详情"), UnknownStateError),
    ],
)
def test_boss_detector_pauses_unsafe_or_unapproved_states(
    snapshot: BossPageSnapshot, error: type[Exception]
) -> None:
    with pytest.raises(error):
        detector.detect(snapshot)


def test_boss_detector_accepts_visible_ready_page() -> None:
    assert detector.detect(
        BossPageSnapshot(url="https://www.zhipin.com/zhaopin/", text="职位搜索 立即沟通")
    ) == BossPageState.READY


def test_boss_detector_does_not_treat_job_copy_as_risk_control() -> None:
    assert detector.detect(
        BossPageSnapshot(
            url="https://www.zhipin.com/zhaopin/",
            text="职位搜索 立即沟通 负责风控策略与模型建设",
        )
    ) == BossPageState.READY


async def test_boss_visible_import_deduplicates_without_raw_html(client: AsyncClient) -> None:
    payload = {
        "page_url": "https://www.zhipin.com/zhaopin/?query=AI",
        "jobs": [
            {
                "external_job_id": "boss-import-001",
                "title": "AI Agent 实习",
                "description": "参与 RAG 与 Browser Agent 开发",
                "job_url": "https://www.zhipin.com/job_detail/boss-import-001.html",
                "location": "北京",
                "company_name": "CareerPilot Labs",
                "salary_text": "5-8K",
                "tags": ["AI", "RAG"],
            }
        ],
    }
    imported = await client.post("/api/platforms/boss/import-visible", json=payload)
    assert imported.status_code == 201
    assert imported.json()["created"] == 1
    assert imported.json()["items"][0]["platform"] == "boss"
    assert imported.json()["items"][0]["source_url"].startswith("https://www.zhipin.com/")
    assert imported.json()["items"][0]["raw_data"]["collection_mode"] == "visible_page_only"
    assert imported.json()["items"][0]["raw_data"]["description_source"] == "card_summary"
    repeated = await client.post("/api/platforms/boss/import-visible", json=payload)
    assert repeated.status_code == 201
    assert repeated.json()["duplicates"] == 1

    full_jd = "负责完整的 AI Agent 与 RAG 功能开发，包括向量检索、评估、上线维护和跨团队协作。"
    payload["jobs"][0]["description"] = full_jd
    payload["jobs"][0]["description_source"] = "detail_panel"
    enriched = await client.post("/api/platforms/boss/import-visible", json=payload)
    assert enriched.status_code == 201
    assert enriched.json()["created"] == 0
    assert enriched.json()["duplicates"] == 1
    assert enriched.json()["updated"] == 1
    enriched_job = enriched.json()["items"][0]
    assert full_jd in enriched_job["description"]
    assert enriched_job["raw_data"]["description_source"] == "detail_panel"
    persisted = await client.get(f"/api/jobs/{enriched_job['id']}")
    assert persisted.status_code == 200
    assert full_jd in persisted.json()["description"]


async def test_recollecting_same_boss_job_refreshes_freshness_and_restores_campaign_eligibility(
    client: AsyncClient,
    monkeypatch,
) -> None:
    old_collection_time = datetime.now(UTC) - timedelta(days=4)
    current_collection_time = datetime.now(UTC)
    monkeypatch.setattr(
        "app.services.boss._utc_now",
        lambda: old_collection_time,
    )
    payload = {
        "page_url": "https://www.zhipin.com/web/geek/jobs?query=RAG",
        "captured_at": current_collection_time.isoformat(),
        "jobs": [
            {
                "external_job_id": "boss-refresh-freshness-001",
                "title": "RAG 工程师",
                "description": "负责 RAG 检索、评估与服务部署",
                "job_url": "https://www.zhipin.com/job_detail/boss-refresh-freshness-001.html",
                "location": "北京",
                "description_source": "detail_panel",
            }
        ],
    }

    first = await client.post("/api/platforms/boss/import-visible", json=payload)
    assert first.status_code == 201
    first_job = first.json()["items"][0]
    assert datetime.fromisoformat(first_job["last_collected_at"]) == old_collection_time
    assert first_job["raw_data"]["captured_at"] == old_collection_time.isoformat()
    assert first_job["raw_data"]["client_captured_at"] == current_collection_time.isoformat()

    resume_id = await _upload_campaign_resume(client)
    stale_campaign = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "Stale BOSS Campaign",
            "resume_id": resume_id,
            "job_ids": [first_job["id"]],
        },
    )
    assert stale_campaign.status_code == 201
    campaign_id = stale_campaign.json()["id"]
    stale_approval = await client.post(
        f"/api/campaigns/{campaign_id}/approve",
        json={"job_ids": [first_job["id"]]},
    )
    assert stale_approval.status_code == 409
    assert "超过 3 天" in stale_approval.json()["detail"]

    monkeypatch.setattr(
        "app.services.boss._utc_now",
        lambda: current_collection_time,
    )
    repeated = await client.post("/api/platforms/boss/import-visible", json=payload)
    assert repeated.status_code == 201
    assert repeated.json()["created"] == 0
    assert repeated.json()["duplicates"] == 1
    refreshed_job = repeated.json()["items"][0]
    assert refreshed_job["id"] == first_job["id"]
    assert datetime.fromisoformat(refreshed_job["last_collected_at"]) == current_collection_time
    assert datetime.fromisoformat(refreshed_job["updated_at"]).replace(
        tzinfo=None
    ) == datetime.fromisoformat(first_job["updated_at"]).replace(tzinfo=None)

    restored_approval = await client.post(
        f"/api/campaigns/{campaign_id}/approve",
        json={"job_ids": [first_job["id"]]},
    )
    assert restored_approval.status_code == 200
    assert restored_approval.json()["queued_count"] == 1


async def test_boss_visible_import_decodes_salary_before_analysis(client: AsyncClient) -> None:
    imported = await client.post(
        "/api/platforms/boss/import-visible",
        json={
            "page_url": "https://www.zhipin.com/web/geek/jobs?query=AI",
            "jobs": [
                {
                    "external_job_id": "boss-private-salary-001",
                    "title": "AI 实习生",
                    "description": "负责 AI Agent 功能开发",
                    "job_url": "https://www.zhipin.com/job_detail/boss-private-salary-001.html",
                    "salary_text": "-元/天",
                    "description_source": "detail_panel",
                }
            ],
        },
    )
    assert imported.status_code == 201
    job = imported.json()["items"][0]
    assert job["raw_data"]["salary_text"] == "150-200元/天"
    assert job["raw_data"]["salary_encoding_decoded"] is True
    assert "Salary: 150-200元/天" in job["description"]
    assert job["salary_min"] == 150
    assert job["salary_max"] == 200


async def _create_queued_boss_application(client: AsyncClient) -> str:
    resume_id = await _upload_campaign_resume(client)
    imported = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": "AI Agent 实习\n\nLocation: 北京\n\nBuild RAG and Browser Agent tools.",
            "platform": "boss",
            "external_job_id": "boss-browser-001",
            "source_url": "https://www.zhipin.com/job_detail/boss-browser-001.html",
        },
    )
    assert imported.status_code == 201
    job_id = imported.json()["items"][0]["job"]["id"]
    campaign = await client.post(
        "/api/campaigns/curated",
        json={
            "name": "BOSS User Curated Campaign",
            "resume_id": resume_id,
            "job_ids": [job_id],
            "query": "AI Agent 北京",
        },
    )
    assert campaign.status_code == 201
    assert campaign.json()["status"] == "WAITING_APPROVAL"
    assert campaign.json()["candidate_jobs"][0]["application"]["status"] == "WAITING_APPROVAL"
    approved = await client.post(
        f"/api/campaigns/{campaign.json()['id']}/approve",
        json={"job_ids": [job_id]},
    )
    assert approved.status_code == 200
    return approved.json()["candidate_jobs"][0]["application"]["id"]


async def test_boss_browser_task_runs_only_through_user_session_adapter(
    client: AsyncClient,
) -> None:
    application_id = await _create_queued_boss_application(client)
    catalog = await client.get("/api/browser-tasks/platforms")
    boss = next(item for item in catalog.json() if item["name"] == "boss")
    assert boss["safe_for_automation"] is False
    created = await client.post(
        "/api/browser-tasks",
        json={
            "application_id": application_id,
            "platform": "boss",
            "scenario": "SUCCESS",
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["payload"]["context"]["credential_boundary"] == "user_browser_session_only"
    assert "www.zhipin.com" in task["payload"]["actions"][0]["url"]
    completed = await client.post(f"/api/browser-tasks/{task['id']}/mock-extension")
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
