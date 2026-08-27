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


def test_job_normalizer_handles_boss_decorated_sections_and_compatibility_glyphs() -> None:
    raw_jd = """后端开发实习生
Company: 小黑盒
Location: 北京·朝阳区·望京
Salary: 300-400元/天
---你需要参与---
1.参与后台系统的设计、开发与维护；
2.参与游戏数据的调研、分析、评估、功能开发以及上线。
---我们对你的要求---
1.本科及以上计算机相关专业在校生，毕业前满足6个⽉+全职实习；
2.熟悉Go或Python，了解分布式系统开发。
---我们为你提供---
1.加入优秀的互联网研发团队，给足挑战与空间；
2.新生培训计划+一对一导师制。
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert analysis.requirements.responsibilities == [
        "参与后台系统的设计、开发与维护；",
        "参与游戏数据的调研、分析、评估、功能开发以及上线。",
    ]
    assert len(analysis.requirements.qualifications) == 2
    assert analysis.requirements.benefits == [
        "加入优秀的互联网研发团队，给足挑战与空间；",
        "新生培训计划+一对一导师制。",
    ]
    assert "本科" in analysis.requirements.education
    assert analysis.structured_job.location == "北京·朝阳区·望京"
    assert "月" in analysis.requirements.education


def test_job_normalizer_extracts_numbered_boss_requirement_sections() -> None:
    raw_jd = """机器人控制算法实习生
岗位职责:
参与人形机器人控制算法调研、仿真训练及真机验证。
一、岗位职责
（一）全身运动控制与动作跟踪研发支持
1. 协助开展 Whole Body Control、动作跟踪及运动控制算法的实现与验证；
2. 参与机器人状态、参考动作与控制指令的设计。
二、岗位要求
1. 本科及以上学历，机器人、自动化、控制科学与工程等相关专业在校学生；
2. 熟练掌握 Python，具备良好的代码阅读、调试和工程实现能力；
3. 具备机器人学基础，了解运动学、动力学、坐标变换等基本概念；
4. 了解强化学习或模仿学习基本原理，熟悉 PPO、Actor-Critic 至少一种方法；
5. 熟悉 PyTorch，能够完成模型搭建、训练、调试及实验分析。
三、加分项
1. 使用过 Isaac Gym、Isaac Lab、MuJoCo 等仿真平台；
2. 有 Sim2Real 或机器人真机部署经验。
四、岗位的重要性
1. 参与前沿人形机器人技术研发，获得导师指导。
五、为什么加入我们
1. 团队提供完整的算法训练与真机实验机会。
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert len(analysis.requirements.qualifications) == 5
    assert "本科" in analysis.requirements.education
    assert "熟练掌握 Python" in analysis.requirements.qualifications[1]
    assert len(analysis.requirements.preferred_qualifications) == 2
    assert all(
        "岗位的重要性" not in item and "为什么加入我们" not in item
        for item in analysis.requirements.preferred_qualifications
    )
    assert len(analysis.requirements.benefits) == 2
    assert {"Python", "PyTorch"}.issubset(
        set(analysis.structured_job.required_skills)
    )


def test_job_normalizer_keeps_plain_boss_lines_and_ignores_label_only_experience() -> None:
    raw_jd = """具身算法实习生
岗位职责：
研发机器人操作算法，提升机器人在复杂场景下的操作能力；
探索端到端操作框架，结合大语言模型实现感知、决策、执行闭环。
任职要求：
硕士或博士在读，机器人学、人工智能、计算机等相关领域；
操作算法经验：
熟悉机器人抓取、装配等操作任务，有灵巧手或双臂协同项目经验者优先；
熟练使用PyTorch/TensorFlow，具备机器人仿真经验者加分；
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert len(analysis.requirements.responsibilities) == 2
    assert len(analysis.requirements.qualifications) == 3
    assert analysis.requirements.experience != "操作算法经验："
    assert "项目经验" in analysis.requirements.experience
    assert {"PyTorch", "TensorFlow"}.issubset(
        set(analysis.structured_job.required_skills)
    )


def test_job_normalizer_infers_unheaded_requirements_and_benefits() -> None:
    raw_jd = """AI 全栈工程师实习生
我们是公司 Agent 开发团队，正在寻找对 AI 和软件开发充满好奇心的在校同学。
你可能适合我们，如果你：
正在就读计算机、软件工程、信息技术等相关专业；
有一定的编程基础，了解前端或后端任意一个方向；
对 AI 工具（如 Cursor、Claude Code、Codex）有使用经验或强烈兴趣。
你将获得：
参与真实客户项目的完整开发经历；
来自团队的一对一指导与反馈。
"""

    analysis = JobNormalizer().analyze(raw_jd)

    assert any("正在就读" in item for item in analysis.requirements.qualifications)
    assert any("编程基础" in item for item in analysis.requirements.qualifications)
    assert analysis.requirements.benefits == [
        "参与真实客户项目的完整开发经历；",
        "来自团队的一对一指导与反馈。",
    ]
    assert analysis.structured_job.role_category == "Full-stack Engineering"


def test_job_normalizer_extracts_skills_seen_in_imported_boss_jds() -> None:
    analysis = JobNormalizer().analyze(
        "算法实习生\n"
        "岗位职责\n参与 AI 算法实现和部署。\n"
        "岗位要求\n熟悉 C/C++、OpenCV、NumPy、PyTorch、ONNX Runtime、ROS2、MCP。"
    )

    skills = set(analysis.structured_job.required_skills)
    assert {"C++", "OpenCV", "NumPy", "PyTorch", "ONNX Runtime", "ROS2", "MCP"}.issubset(
        skills
    )
    assert "C" not in skills


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
