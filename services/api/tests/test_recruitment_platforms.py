from __future__ import annotations

from httpx import AsyncClient

from app.platforms.domain import JobSearchQuery
from app.platforms.fingerprint import job_fingerprint
from app.platforms.location import split_location
from app.platforms.salary import parse_salary_text
from app.platforms.zhaopin.detectors import ZhaopinDetector, ZhaopinPageSnapshot, ZhaopinPageState
from app.platforms.zhaopin.parser import parse_zhaopin_payload
from app.platforms.zhaopin.provider import ZhaopinProvider


def test_salary_and_location_normalization() -> None:
    salary = parse_salary_text("15K-25K·14薪")
    assert salary.minimum == 15_000
    assert salary.maximum == 25_000
    assert salary.months == 14
    assert parse_salary_text("1.5-2万").minimum == 15_000
    assert parse_salary_text("面议").maximum is None
    assert split_location("武汉·洪山区").city == "武汉"
    assert split_location("武汉·洪山区").district == "洪山区"


def test_zhaopin_html_payload_is_normalized() -> None:
    html = """
    <div class="job-list-item" data-job-id="zp-001">
      <a class="job-title" href="/jobdetail/zp-001.html">大模型算法工程师</a>
      <span class="company-name">智联未来</span>
      <span class="salary">15K-25K·14薪</span>
      <span class="job-location">武汉·洪山区</span>
      <span class="experience">1-3年</span>
      <span class="education">本科</span>
      <div class="job-desc">负责 RAG 检索增强生成和 Agent 应用落地。</div>
    </div>
    """
    jobs = parse_zhaopin_payload(html, page_url="https://www.zhaopin.com/sou/")
    assert len(jobs) == 1
    provider = ZhaopinProvider.__new__(ZhaopinProvider)
    normalized = provider._normalize(jobs[0], page_url="https://www.zhaopin.com/sou/")
    assert normalized.external_job_id == "zp-001"
    assert normalized.salary_min == 15_000
    assert normalized.salary_max == 25_000
    assert normalized.education == "本科"
    assert "RAG" in normalized.description


def test_zhaopin_json_payload_and_url_reference() -> None:
    jobs = parse_zhaopin_payload(
        {
            "data": {
                "results": [
                    {
                        "jobId": "zp-002",
                        "jobName": "机器人控制算法实习生",
                        "salary": "8-12K",
                        "degree": "本科",
                        "jd": "负责控制算法开发与调试",
                        "url": "/jobdetail/zp-002.html",
                    }
                ]
            }
        },
        page_url="https://www.zhaopin.com/web/search/",
    )
    assert jobs[0].title == "机器人控制算法实习生"
    assert jobs[0].source_url.endswith("/jobdetail/zp-002.html")
    provider = ZhaopinProvider.__new__(ZhaopinProvider)
    reference = provider.extract_job_reference("https://www.zhaopin.com/jobdetail/zp-002.html")
    assert reference.external_job_id == "zp-002"


def test_zhaopin_detector_exposes_safe_page_states() -> None:
    detector = ZhaopinDetector()
    ready = detector.detect(
        ZhaopinPageSnapshot(
            url="https://www.zhaopin.com/web/search/",
            text="职位搜索 大模型算法工程师 15K-25K",
        )
    )
    assert ready == ZhaopinPageState.READY
    try:
        detector.detect(
            ZhaopinPageSnapshot(
                url="https://www.zhaopin.com/web/search/",
                text="请先登录后查看职位",
            )
        )
    except Exception as exc:
        assert "登录" in str(exc)
    else:
        raise AssertionError("login page should not be treated as ready")


def test_fingerprint_is_cross_platform_stable() -> None:
    left = job_fingerprint(company_name="智联未来", title="RAG 工程师", city="武汉")
    right = job_fingerprint(company_name="智联未来", title="rag 工程师", city="武汉市")
    assert left == right
    assert JobSearchQuery(platforms=(" BOSS ", "boss", "zhaopin")).normalized_platforms == (
        "boss",
        "zhaopin",
    )


async def test_zhaopin_platform_catalog_and_visible_import_are_persistent(
    client: AsyncClient,
) -> None:
    catalog = await client.get("/api/platforms")
    assert catalog.status_code == 200
    assert {item["id"] for item in catalog.json()} >= {"boss", "zhaopin"}

    payload = {
        "page_url": "https://www.zhaopin.com/web/search/?kw=RAG",
        "jobs": [
            {
                "external_job_id": "api-zp-001",
                "title": "机器人控制算法实习生",
                "description": "负责运动控制算法开发、仿真和测试。",
                "job_url": "https://www.zhaopin.com/jobdetail/api-zp-001.html",
                "location": "武汉·洪山区",
                "company_name": "智联未来",
                "salary_text": "8-12K",
                "experience": "应届",
                "education": "本科",
                "requirements": ["Python"],
                "skills": ["控制算法"],
                "benefits": [],
            }
        ],
    }
    imported = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
    assert imported.status_code == 201
    body = imported.json()
    assert body["created"] == 1
    assert body["items"][0]["platform"] == "zhaopin"
    assert body["items"][0]["salary_min"] == 8000
    assert body["items"][0]["platform_metadata"]["source"] == "zhaopin_visible_page"

    repeated = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
    assert repeated.status_code == 201
    assert repeated.json()["created"] == 0
    assert repeated.json()["duplicates"] == 1

    searched = await client.post(
        "/api/platforms/search",
        json={"keyword": "机器人控制", "platforms": ["zhaopin"], "page_size": 20},
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["platform_status"]["zhaopin"]["status"] == "success"


async def test_zhaopin_full_detail_replaces_long_summary_and_shorter_changed_jd(
    client: AsyncClient,
) -> None:
    item = {
        "external_job_id": "detail-refresh", "title": "RAG工程师",
        "description": "列表混杂的推荐信息。" * 50,
        "job_url": "https://www.zhaopin.com/jobdetail/detail-refresh.htm",
        "company_name": "测试公司", "salary_text": "10-20K",
        "education": "本科", "experience": "1-3年",
        "raw_data": {"description_source": "card_summary"},
    }
    payload = {"page_url": "https://www.zhaopin.com/sou?kw=RAG", "jobs": [item]}
    initial = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
    assert initial.status_code == 201
    job_id = initial.json()["items"][0]["id"]
    item["raw_data"] = {
        "description_source": "detail_page", "parser_version": "zhaopin-dom-2026-09-04"
    }
    descriptions = (
        "工作职责\n负责 RAG 检索系统开发。\n任职要求\n熟悉 Python、向量检索及评测。",
        "工作职责\n开发 RAG。\n任职要求\n熟悉 Python。",
    )
    for description in descriptions:
        item["description"] = description
        refreshed = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
        assert refreshed.status_code == 201
        body = refreshed.json()
        assert body["updated"] == 1
        stored = body["items"][0]
        assert stored["id"] == job_id
        assert description in stored["description"]
        assert "推荐信息" not in stored["description"]
        assert stored["raw_data"]["description_source"] == "detail_page"
        assert stored["platform_metadata"]["description_source"] == "detail_page"
        assert stored["education_requirement"] == "本科"
        assert stored["salary_min"] == 10000
        assert stored["last_collected_at"]
    repeated = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
    assert repeated.json()["updated"] == 0
    item["description"] = "摘要内容" * 200
    item["raw_data"] = {"description_source": "card_summary"}
    summary_again = await client.post("/api/platforms/zhaopin/import-visible", json=payload)
    assert summary_again.json()["updated"] == 0
    assert "摘要内容" not in summary_again.json()["items"][0]["description"]
