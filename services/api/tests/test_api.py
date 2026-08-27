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


async def test_job_list_supports_combined_filters_and_page_navigation(
    client: AsyncClient,
) -> None:
    jobs = [
        {
            "platform": "boss",
            "external_job_id": "filter-001",
            "title": "RAG Agent 实习生",
            "description": "使用 Python 构建企业知识库",
            "location": "北京·海淀区",
            "salary_min": 300,
            "salary_max": 500,
            "education_requirement": "本科及以上",
            "experience_requirement": "1-3 年或优秀应届生",
            "raw_data": {"company_name": "星河智能"},
        },
        {
            "platform": "manual",
            "external_job_id": "filter-002",
            "title": "Java 后端工程师",
            "description": "负责交易系统开发",
            "location": "上海",
            "salary_min": 200,
            "salary_max": 280,
            "education_requirement": "大专",
            "experience_requirement": "3-5 年",
            "raw_data": {"company_name": "云帆科技"},
        },
        {
            "platform": "boss",
            "external_job_id": "filter-003",
            "title": "机器人算法实习生",
            "description": "运动规划与控制算法",
            "location": "深圳",
            "salary_min": 150,
            "salary_max": 250,
            "education_requirement": "硕士",
            "experience_requirement": "经验不限",
            "raw_data": {"company_name": "动力未来"},
        },
    ]
    for payload in jobs:
        assert (await client.post("/api/jobs", json=payload)).status_code == 201

    filtered = await client.get(
        "/api/jobs",
        params={
            "search": "RAG",
            "company": "星河",
            "location": "北京",
            "platform": "boss",
            "education": "本科",
            "experience": "应届",
            "salary_floor": 350,
            "salary_ceiling": 450,
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["external_job_id"] == "filter-001"

    second_page = await client.get("/api/jobs", params={"page": 2, "page_size": 1})
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 3
    assert second_page.json()["page"] == 2
    assert len(second_page.json()["items"]) == 1

    invalid_range = await client.get(
        "/api/jobs", params={"salary_floor": 500, "salary_ceiling": 300}
    )
    assert invalid_range.status_code == 422
