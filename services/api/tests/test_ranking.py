from httpx import AsyncClient


async def _upload_ranking_resume(client: AsyncClient) -> str:
    resume_text = """Alex Chen

Summary
Backend Engineer with 5 years of Python, FastAPI, PostgreSQL, Redis, Docker, RAG, and LLM.

Experience
Acme - Backend Engineer | 2020 - 2025
- Built FastAPI services, PostgreSQL data pipelines, and semantic retrieval systems.

Skills
Python, FastAPI, PostgreSQL, Redis, Docker, RAG, LLM, SQL

Education
Bachelor's degree in Computer Science
"""
    response = await client.post(
        "/api/resumes",
        files={"file": ("ranking-resume.txt", resume_text.encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_ranking_jobs(client: AsyncClient) -> list[str]:
    jobs = [
        ("Backend Platform Engineer", "Python, FastAPI, PostgreSQL, Redis, and Docker"),
        ("RAG Engineer", "Python, RAG, LLM, vector search, and PostgreSQL"),
        ("Data Engineer", "Python, SQL, PostgreSQL, ETL, and Docker"),
        ("API Engineer", "Python, FastAPI, Redis, REST APIs, and Docker"),
        ("Frontend Engineer", "TypeScript, React, Next.js, CSS, and Figma"),
        ("Mobile Engineer", "Kotlin, Android, Jetpack Compose, and Firebase"),
        ("iOS Engineer", "Swift, SwiftUI, UIKit, and Combine"),
        ("Game Engineer", "C++, Unreal Engine, graphics, and multiplayer systems"),
    ]
    ids: list[str] = []
    for index, (title, skills) in enumerate(jobs, start=1):
        response = await client.post(
            "/api/jobs/import",
            json={
                "raw_jd": (
                    f"{title}\n\nLocation: Remote\n\nResponsibilities\n"
                    f"- Build production systems for role {index}.\n\nRequirements\n"
                    f"- Bachelor's degree.\n- 3+ years of experience.\n- {skills}."
                ),
                "platform": "ranking-test",
                "external_job_id": f"ranking-{index:03d}",
            },
        )
        assert response.status_code == 201
        ids.append(response.json()["items"][0]["job"]["id"])
    return ids


async def test_ranking_pipeline_reduces_candidates_and_returns_full_trace(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_ranking_resume(client)
    job_ids = await _import_ranking_jobs(client)

    response = await client.post(
        "/api/jobs/rank",
        json={
            "resume_id": resume_id,
            "job_ids": job_ids,
            "candidate_limit": 8,
            "top_k_embedding": 6,
            "top_k_rerank": 4,
            "top_k_llm": 3,
            "final_top_k": 2,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total_candidates"] == 8
    assert len(result["items"]) == 2
    assert [item["rank"] for item in result["items"]] == [1, 2]
    assert result["items"][0]["score"]["final_score"] >= result["items"][1]["score"][
        "final_score"
    ]
    assert all(item["score"]["score_version"] == "RANKING_V1" for item in result["items"])

    trace = result["trace"]
    assert trace["version"] == "RANKING_V1"
    assert trace["llm_calls"] == 4
    assert [stage["name"] for stage in trace["stages"]] == [
        "rule_filter",
        "embedding_rank",
        "reranker",
        "llm_judge",
        "final_ranking",
    ]
    assert [(stage["input_count"], stage["output_count"]) for stage in trace["stages"]] == [
        (8, 8),
        (8, 6),
        (6, 4),
        (4, 3),
        (3, 2),
    ]
    assert all(
        len(stage["candidates"]) == stage["input_count"] for stage in trace["stages"]
    )
    assert all(stage["duration_ms"] >= 0 for stage in trace["stages"])


async def test_ranking_requires_an_available_resume(client: AsyncClient) -> None:
    job_ids = await _import_ranking_jobs(client)

    response = await client.post(
        "/api/jobs/rank",
        json={"job_ids": job_ids, "candidate_limit": 8},
    )

    assert response.status_code == 409
    assert "resume" in response.json()["detail"].lower()
