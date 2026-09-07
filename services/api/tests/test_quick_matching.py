from httpx import AsyncClient


async def _upload_resume(client: AsyncClient) -> str:
    response = await client.post(
        "/api/resumes",
        files={
            "file": (
                "quick-score-resume.txt",
                b"""Alex Chen

Summary
Python backend engineer with FastAPI, RAG, LLM and PostgreSQL experience.

Experience
Acme - Backend Engineer | 2020 - 2025
- Built production APIs and retrieval services.

Skills
Python, FastAPI, RAG, LLM, PostgreSQL

Education
Bachelor's degree in Computer Science
""",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_job(client: AsyncClient, external_id: str, requirements: str) -> str:
    return await _import_titled_job(client, external_id, "AI Agent Engineer", requirements)


async def _import_titled_job(
    client: AsyncClient, external_id: str, title: str, requirements: str
) -> str:
    response = await client.post(
        "/api/jobs/import",
        json={
            "raw_jd": (
                f"{title}\n\nLocation: Remote\n\n"
                "Responsibilities\n- Build retrieval services.\n\n"
                f"Requirements\n- {requirements}."
            ),
            "platform": "quick-score-test",
            "external_job_id": external_id,
        },
    )
    assert response.status_code == 201
    return response.json()["items"][0]["job"]["id"]


async def test_quick_score_is_deterministic_cached_and_does_not_call_llm(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    strong_job_id = await _import_job(
        client,
        "quick-strong",
        "Python, FastAPI, RAG, LLM, PostgreSQL, Bachelor's degree",
    )
    weak_job_id = await _import_job(
        client,
        "quick-weak",
        "Kotlin, Android, Firebase, Master's degree",
    )

    first = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [strong_job_id, weak_job_id]},
    )
    assert first.status_code == 200
    items = {item["job_id"]: item for item in first.json()["items"]}
    assert items[strong_job_id]["score"] > items[weak_job_id]["score"]
    assert items[strong_job_id]["cached"] is False
    assert items[weak_job_id]["cached"] is False

    repeated = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [strong_job_id, weak_job_id]},
    )
    assert repeated.status_code == 200
    repeated_items = {item["job_id"]: item for item in repeated.json()["items"]}
    assert repeated_items[strong_job_id]["cached"] is True
    assert repeated_items[weak_job_id]["cached"] is True


async def test_quick_score_v3_caps_cross_function_false_positive(client: AsyncClient) -> None:
    resume_id = await _upload_resume(client)
    sales_job_id = await _import_titled_job(
        client,
        "quick-ai-sales",
        "AI SaaS 销售实习生",
        "熟悉 AI Agent 和 Prompt，有客户拓展与商务沟通能力",
    )
    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [sales_job_id]},
    )
    assert response.status_code == 200
    score = response.json()["items"][0]
    assert score["score"] <= 35
    assert score["direction_score"] == 15
    assert score["hard_constraint_passed"] is False
    assert score["recommendation"] == "skip"
    assert any(item["requirement_type"] == "direction" for item in score["requirement_matches"])


async def test_quick_score_v3_applies_hard_constraint_caps_without_duplicate_penalty(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_titled_job(
        client,
        "quick-hard-caps",
        "Backend Engineer",
        "必须精通 Kotlin，要求 Master's degree，10 years experience",
    )
    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [job_id]},
    )
    assert response.status_code == 200
    score = response.json()["items"][0]
    assert score["score"] <= 40
    assert score["hard_constraint_passed"] is False
    missing = [item for item in score["requirement_matches"] if item["status"] == "missing"]
    skill_gaps = [item for item in missing if item["requirement_type"] == "must_have_skill"]
    assert skill_gaps
    assert all(item["deduction"] == 0 for item in skill_gaps)
    assert sum(
        entry["reason"] == "critical_skill_missing"
        for entry in score["hard_constraint_ledger"]
    ) == 1
    assert any("关键必备技能" in reason for reason in score["rule_reasons"])
    assert any("学历" in reason for reason in score["rule_reasons"])
    assert any("经验" in reason for reason in score["rule_reasons"])


async def test_quick_score_v3_treats_at_least_one_skill_as_any_of(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_titled_job(
        client,
        "quick-any-of",
        "Backend Engineer",
        "必须掌握 Python / Java / Go / TypeScript 至少一种",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    alternatives = [
        item
        for item in score["requirement_matches"]
        if item["requirement_value"] in {"Python", "Java", "Go", "TypeScript"}
    ]
    assert alternatives
    assert any(item["status"] == "matched" for item in alternatives)
    assert not any(item["status"] == "missing" for item in alternatives)
    assert not any(
        entry["reason"] == "must_have_skill_missing"
        for entry in score["hard_constraint_ledger"]
    )


async def test_quick_score_v3_accepts_bachelor_or_master_requirement(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_titled_job(
        client,
        "quick-education-any-of",
        "AI Application Engineer",
        "计算机相关专业本科/硕士在读，熟悉 Python",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    education = [
        item
        for item in score["requirement_matches"]
        if item["requirement_type"] == "education"
    ]
    assert education and education[0]["status"] == "matched"
    assert not any(
        entry["reason"] == "education_missing"
        for entry in score["hard_constraint_ledger"]
    )


async def test_quick_score_v3_keeps_bachelor_minimum_when_master_is_preferred(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_titled_job(
        client,
        "quick-bachelor-minimum",
        "Robot Algorithm Intern",
        "本科及以上学历，计算机相关专业在校学生，硕士研究生优先",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    education = next(
        item
        for item in score["requirement_matches"]
        if item["requirement_type"] == "education"
    )
    assert education["status"] == "matched"
    assert not any(
        entry["reason"] == "education_missing"
        for entry in score["hard_constraint_ledger"]
    )


async def test_quick_score_v3_matches_cross_language_skill_aliases(
    client: AsyncClient,
) -> None:
    resume = await client.post(
        "/api/resumes",
        files={
            "file": (
                "alias-resume.txt",
                """候选人

项目经历
使用大语言模型实现智能体，并完成工具调用、参数校验和结果回传。

技能
Python，AI Agent

教育经历
计算机科学本科学历
""".encode(),
                "text/plain",
            )
        },
    )
    job_id = await _import_titled_job(
        client,
        "quick-alias-evidence",
        "AI Agent Engineer",
        "必须掌握 LLM 和 Function Calling",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume.json()["id"], "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    matches = {
        item["requirement_value"]: item
        for item in score["requirement_matches"]
        if item["requirement_type"] == "must_have_skill"
    }
    assert matches["LLM"]["status"] == "matched"
    assert matches["Function Calling"]["status"] == "matched"
    assert not score["missing_skills"]


async def test_quick_score_v3_marks_sparse_jd_as_insufficient_data(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    job_id = await _import_titled_job(
        client,
        "quick-sparse-jd",
        "Backend Engineer",
        "团队氛围良好",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    assert score["score_status"] == "INSUFFICIENT_DATA"
    assert score["score_confidence"] <= 0.35


async def test_quick_score_v3_supports_at_least_n_skill_groups(
    client: AsyncClient,
) -> None:
    resume = await client.post(
        "/api/resumes",
        files={
            "file": (
                "frontend-resume.txt",
                b"Frontend Engineer with React and Vue project experience. Bachelor degree.",
                "text/plain",
            )
        },
    )
    job_id = await _import_titled_job(
        client,
        "quick-at-least-two",
        "Frontend Engineer",
        "至少掌握 React、Vue、Angular 中两项",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume.json()["id"], "job_ids": [job_id]},
    )

    assert response.status_code == 200
    score = response.json()["items"][0]
    assert {"React", "Vue"}.issubset(set(score["matched_skills"]))
    assert "Angular" not in score["missing_skills"]
    assert not score["hard_constraint_ledger"]


async def test_quick_score_v3_does_not_make_preferred_or_context_skills_hard(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    preferred_id = await _import_titled_job(
        client,
        "quick-preferred-skill",
        "Backend Engineer",
        "熟悉 LangGraph 者优先",
    )
    context_id = await _import_titled_job(
        client,
        "quick-context-skill",
        "Backend Engineer",
        "团队目前使用 Go 和 Kubernetes",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [preferred_id, context_id]},
    )

    assert response.status_code == 200
    scores = {item["job_id"]: item for item in response.json()["items"]}
    assert not scores[preferred_id]["hard_constraint_ledger"]
    assert not scores[context_id]["hard_constraint_ledger"]
    assert "LangGraph" not in scores[preferred_id]["missing_skills"]
    assert not {"Go", "Kubernetes"}.intersection(scores[context_id]["missing_skills"])


async def test_quick_score_v3_recognizes_product_assistant_and_teaching_directions(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_resume(client)
    product_id = await _import_titled_job(
        client,
        "quick-product-assistant",
        "Agent 产品助理",
        "了解 LLM 与 RAG，协助整理产品需求",
    )
    teacher_id = await _import_titled_job(
        client,
        "quick-ai-instructor",
        "大模型应用开发讲师",
        "熟悉 Python、LLM 与 RAG，负责课程授课",
    )
    trainer_id = await _import_titled_job(
        client,
        "quick-ai-trainer",
        "AI 训练师 / 智能客服训练师",
        "了解 LLM 与 Prompt，负责整理客服语料",
    )

    response = await client.post(
        "/api/jobs/quick-score",
        json={"resume_id": resume_id, "job_ids": [product_id, teacher_id, trainer_id]},
    )

    assert response.status_code == 200
    scores = {item["job_id"]: item for item in response.json()["items"]}
    assert scores[product_id]["score"] <= 35
    assert scores[teacher_id]["score"] <= 35
    assert scores[trainer_id]["score"] <= 35
    assert scores[product_id]["direction_score"] == 15
    assert scores[teacher_id]["direction_score"] == 15
    assert scores[trainer_id]["direction_score"] == 15
