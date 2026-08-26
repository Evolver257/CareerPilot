from httpx import AsyncClient

from app.services.job_intelligence import JobNormalizer


def test_job_normalizer_extracts_structured_job_skills_and_requirements() -> None:
    raw_jd = """Senior Backend Engineer

Location: Remote

Responsibilities
- Build FastAPI services for a global product.
- Improve PostgreSQL reliability and observability.

Requirements
- Bachelor's degree in Computer Science.
- 5+ years of backend experience.
- Python, FastAPI, PostgreSQL, and Docker.

Preferred Qualifications
- Experience with RAG and LLM applications.
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert analysis.structured_job.title == "Senior Backend Engineer"
    assert analysis.structured_job.role_category == "Backend Engineering"
    assert "Python" in analysis.structured_job.required_skills
    assert "RAG" in analysis.structured_job.preferred_skills
    assert "Bachelor's degree in Computer Science." in analysis.requirements.education
    assert "5+ years of backend experience." in analysis.requirements.experience
    assert len(analysis.requirements.responsibilities) == 2
    assert "Python, FastAPI, PostgreSQL, and Docker." in analysis.requirements.qualifications


def test_job_normalizer_supports_boss_chinese_sections_and_numbered_items() -> None:
    raw_jd = """AI Agent 工程师
【职位描述】：负责企业知识库与智能问答产品研发。
【岗位职责】
1. 负责 RAG 检索链路和 Agent 工作流开发
2、建设 FastAPI 服务并持续优化效果
【任职要求】：
1、本科及以上学历，计算机相关专业
2. 熟悉 Python、FastAPI、SpringBoot、MyBatisPlus 与 PostgreSQL
3、有 2 年以上大模型应用开发经验
【加分项】
· 有 LangChain 或 LlamaIndex 项目经验
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert analysis.structured_job.summary == "负责企业知识库与智能问答产品研发。"
    assert analysis.requirements.responsibilities == [
        "负责 RAG 检索链路和 Agent 工作流开发",
        "建设 FastAPI 服务并持续优化效果",
    ]
    assert len(analysis.requirements.qualifications) == 3
    assert analysis.requirements.preferred_qualifications == [
        "有 LangChain 或 LlamaIndex 项目经验"
    ]
    assert "本科" in analysis.requirements.education
    assert "2 年以上" in analysis.requirements.experience
    assert {"Spring Boot", "MyBatis", "Agent", "LangChain"}.issubset(
        set(analysis.structured_job.required_skills)
        | set(analysis.structured_job.preferred_skills)
    )


def test_job_normalizer_extracts_boss_markdown_work_section() -> None:
    raw_jd = """全栈实习生
职位描述
我们正在寻找有潜力的全栈研发实习生。
---
## 你将参与的工作
1. 参与 Python 后端服务开发，包括业务逻辑、API 接口、数据处理、脚本工具等。
2. 在导师指导下，使用 FastAPI、Flask、Django 等框架完成 Web 后端功能开发。
3. 使用 Vue.js 或其他前端框架，参与简单页面、交互逻辑和管理后台功能开发。
## 任职要求
1. 本科或研究生在读，计算机相关专业优先。
2. 具备良好的 Python 编程基础。
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert analysis.requirements.responsibilities == [
        "参与 Python 后端服务开发，包括业务逻辑、API 接口、数据处理、脚本工具等。",
        "在导师指导下，使用 FastAPI、Flask、Django 等框架完成 Web 后端功能开发。",
        "使用 Vue.js 或其他前端框架，参与简单页面、交互逻辑和管理后台功能开发。",
    ]
    assert analysis.requirements.qualifications == [
        "本科或研究生在读，计算机相关专业优先。",
        "具备良好的 Python 编程基础。",
    ]


def test_job_normalizer_supports_single_digit_k_salary_range() -> None:
    analysis = JobNormalizer().analyze("Backend Engineer\nSalary: 3-5K")
    assert analysis.structured_job.salary.minimum == 3
    assert analysis.structured_job.salary.maximum == 5


async def test_import_and_analyze_job_endpoints(client: AsyncClient) -> None:
    raw_jd = """AI Platform Engineer

Requirements
- 3+ years of experience with Python and FastAPI.
- PostgreSQL and Docker required.

Responsibilities
- Build RAG services for job seekers.
"""
    imported = await client.post(
        "/api/jobs/import",
        json={"raw_jd": raw_jd, "platform": "manual", "external_job_id": "jd-001"},
    )

    assert imported.status_code == 201
    payload = imported.json()
    assert payload["created"] == 1
    assert payload["duplicates"] == 0
    assert payload["items"][0]["structured_job"]["title"] == "AI Platform Engineer"
    assert "Python" in payload["items"][0]["structured_job"]["required_skills"]
    assert payload["items"][0]["requirements"]["responsibilities"]
    assert payload["items"][0]["skills"]

    duplicate = await client.post(
        "/api/jobs/import",
        json={"raw_jd": raw_jd, "platform": "manual", "external_job_id": "jd-001"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] == 0
    assert duplicate.json()["duplicates"] == 1

    job_id = payload["items"][0]["job"]["id"]
    analyzed = await client.post(f"/api/jobs/{job_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["structured_job"]["role_category"] == "Backend Engineering"


async def test_mock_jobs_import_provides_dozens_of_deduplicated_jobs(client: AsyncClient) -> None:
    imported = await client.post("/api/jobs/import", json={"mode": "mock", "limit": 30})

    assert imported.status_code == 201
    payload = imported.json()
    assert payload["created"] == 30
    assert payload["total"] == 30
    assert all(item["job"]["platform"] == "mock" for item in payload["items"])
    assert all(item["skills"] for item in payload["items"])

    repeated = await client.post("/api/jobs/import", json={"mode": "mock", "limit": 30})
    assert repeated.status_code == 201
    assert repeated.json()["created"] == 0
    assert repeated.json()["duplicates"] == 30
