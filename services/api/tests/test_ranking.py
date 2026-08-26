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

    payload = {
        "resume_id": resume_id,
        "job_ids": job_ids,
        "candidate_limit": 8,
        "top_k_embedding": 6,
        "top_k_rerank": 4,
        "top_k_llm": 3,
        "final_top_k": 2,
    }
    response = await client.post("/api/jobs/rank", json=payload)

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

    cached_response = await client.post("/api/jobs/rank", json=payload)
    assert cached_response.status_code == 200
    cached_trace = cached_response.json()["trace"]
    assert cached_trace["cache_hits"] == 4
    assert cached_trace["llm_calls"] == 0
    assert [item["score"]["id"] for item in cached_response.json()["items"]] == [
        item["score"]["id"] for item in result["items"]
    ]


async def test_fast_ranking_skips_llm_and_caches_deterministic_scores(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_ranking_resume(client)
    job_ids = await _import_ranking_jobs(client)
    payload = {
        "resume_id": resume_id,
        "job_ids": job_ids,
        "candidate_limit": 8,
        "top_k_embedding": 6,
        "top_k_rerank": 4,
        "top_k_llm": 3,
        "final_top_k": 2,
        "scoring_mode": "fast",
    }

    response = await client.post("/api/jobs/rank", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["trace"]["config"]["scoring_mode"] == "fast"
    assert result["trace"]["llm_calls"] == 0
    assert result["trace"]["fallback_count"] == 0
    assert result["trace"]["token_usage"]["total_tokens"] == 0
    assert [stage["name"] for stage in result["trace"]["stages"]] == [
        "rule_filter",
        "embedding_rank",
        "reranker",
        "deterministic_rank",
        "final_ranking",
    ]
    assert all(item["score"]["judge_source"] == "deterministic" for item in result["items"])
    assert all(item["score"]["llm_score"] == 0 for item in result["items"])
    assert all("llm" not in item["score"]["weights"] for item in result["items"])

    cached = await client.post("/api/jobs/rank", json=payload)

    assert cached.status_code == 200
    assert cached.json()["trace"]["cache_hits"] == 4
    assert cached.json()["trace"]["llm_calls"] == 0


async def test_ranking_requires_an_available_resume(client: AsyncClient) -> None:
    job_ids = await _import_ranking_jobs(client)

    response = await client.post(
        "/api/jobs/rank",
        json={"job_ids": job_ids, "candidate_limit": 8},
    )

    assert response.status_code == 409
    assert "resume" in response.json()["detail"].lower()


async def test_async_ranking_run_returns_pollable_persisted_status(
    client: AsyncClient,
    monkeypatch,
) -> None:
    resume_id = await _upload_ranking_resume(client)

    async def skip_execution(_run_id) -> None:
        return None

    monkeypatch.setattr("app.api.jobs.execute_ranking_run", skip_execution)
    response = await client.post(
        "/api/jobs/rank-runs",
        json={"resume_id": resume_id},
    )

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "PENDING"
    assert run["stage"] == "queued"

    polled = await client.get(f"/api/jobs/rank-runs/{run['id']}")
    assert polled.status_code == 200
    assert polled.json()["id"] == run["id"]

    premature_result = await client.get(f"/api/jobs/rank-runs/{run['id']}/result")
    assert premature_result.status_code == 409
