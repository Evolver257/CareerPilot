from httpx import AsyncClient

from app.services.agent_runtime import AgentPlanner


async def _upload_agent_resume(client: AsyncClient) -> str:
    response = await client.post(
        "/api/resumes",
        files={
            "file": (
                "agent-resume.txt",
                b"""Alex Chen

Summary
AI Agent engineer with Python, FastAPI, RAG, LLM, and vector search experience.

Experience
Acme - AI Engineer | 2022 - 2025
- Built production agent orchestration and retrieval systems.

Skills
Python, FastAPI, RAG, LLM, PostgreSQL, Docker
""",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _import_agent_jobs(client: AsyncClient) -> None:
    requirements = [
        "Python, FastAPI, RAG, LLM, and AI Agent workflows",
        "Python, vector search, RAG, and PostgreSQL",
        "Python, LLM evaluation, Docker, and FastAPI",
        "TypeScript, React, Next.js, and CSS",
        "Java, Spring Boot, and Kafka",
    ]
    for index, skills in enumerate(requirements, start=1):
        response = await client.post(
            "/api/jobs/import",
            json={
                "raw_jd": (
                    f"AI Agent Intern {index}\n\nLocation: Remote\n\n"
                    "Responsibilities\n- Build production AI systems.\n\nRequirements\n"
                    f"- Internship or graduate role.\n- {skills}."
                ),
                "platform": "agent-test",
                "external_job_id": f"agent-{index:03d}",
            },
        )
        assert response.status_code == 201


async def test_agent_run_executes_trace_and_resumes_after_approval(
    client: AsyncClient,
) -> None:
    resume_id = await _upload_agent_resume(client)
    await _import_agent_jobs(client)

    tools = await client.get("/api/agent-runs/tools")
    assert tools.status_code == 200
    assert {item["name"] for item in tools.json()} == {
        "search_jobs",
        "get_job",
        "analyze_job",
        "retrieve_resume",
        "score_job",
        "rank_jobs",
        "create_campaign",
        "queue_application",
        "request_approval",
    }
    assert all(item["input_schema"] and item["output_schema"] for item in tools.json())

    created = await client.post(
        "/api/agent-runs",
        json={
            "goal": "帮我找匹配度 0 分以上、最多 3 个 AI Agent 实习岗位",
            "resume_id": resume_id,
            "max_steps": 12,
        },
    )
    assert created.status_code == 201
    run = created.json()
    run_id = run["id"]
    assert run["status"] == "WAITING_FOR_USER"
    assert [step["tool_name"] for step in run["steps"]] == [
        "search_jobs",
        "analyze_job",
        "retrieve_resume",
        "rank_jobs",
        "create_campaign",
        "request_approval",
    ]
    assert all(step["status"] == "COMPLETED" for step in run["steps"])
    assert all(step["latency_ms"] >= 0 for step in run["steps"])
    assert run["campaign_id"]
    assert run["output"]["user_action_required"] is True
    candidates = run["output"]["candidates"]
    assert len(candidates) == 3
    assert all(candidate["score_id"] for candidate in candidates)
    assert any(event["event_type"] == "USER_ACTION_REQUIRED" for event in run["events"])

    event_stream = await client.get(f"/api/agent-runs/{run_id}/events/stream")
    assert event_stream.status_code == 200
    assert event_stream.headers["content-type"].startswith("text/event-stream")
    assert "event: USER_ACTION_REQUIRED" in event_stream.text
    assert "event: AGENT_STEP_FINISHED" in event_stream.text

    selected = [item["job_id"] for item in candidates[:2]]
    resumed = await client.post(
        f"/api/agent-runs/{run_id}/resume",
        json={"approved": True, "selected_job_ids": selected},
    )
    assert resumed.status_code == 200
    completed = resumed.json()
    assert completed["status"] == "COMPLETED"
    assert completed["output"]["queued_count"] == 2
    assert completed["steps"][-1]["tool_name"] == "queue_application"

    persisted = await client.get(f"/api/agent-runs/{run_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "COMPLETED"
    assert persisted.json()["steps"][-1]["sequence"] == 7

    campaign = await client.get(f"/api/campaigns/{run['campaign_id']}")
    assert campaign.status_code == 200
    assert campaign.json()["status"] == "RUNNING"
    assert campaign.json()["queued_count"] == 2


async def test_agent_run_pause_resume_cancel_and_step_limit(client: AsyncClient) -> None:
    resume_id = await _upload_agent_resume(client)
    await _import_agent_jobs(client)

    created = await client.post(
        "/api/agent-runs",
        json={
            "goal": "找最多 2 个 AI Agent 实习岗位，匹配度 0 分以上",
            "resume_id": resume_id,
            "auto_start": False,
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    assert created.json()["status"] == "PENDING"

    paused = await client.post(f"/api/agent-runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    resumed = await client.post(f"/api/agent-runs/{run_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "WAITING_FOR_USER"

    cancelled = await client.post(f"/api/agent-runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    limited = await client.post(
        "/api/agent-runs",
        json={
            "goal": "找 AI Agent 实习岗位，匹配度 0 分以上",
            "resume_id": resume_id,
            "max_steps": 2,
            "max_retries": 0,
        },
    )
    assert limited.status_code == 201
    assert limited.json()["status"] == "FAILED"
    assert limited.json()["error"] == "Agent reached max_steps"
    assert len(limited.json()["steps"]) == 2


def test_agent_planner_extracts_phase_seven_acceptance_goal() -> None:
    state = AgentPlanner().create_state("帮我找匹配度 80 分以上的 AI Agent 实习岗位")

    assert state.criteria["min_score"] == 80
    assert state.criteria["keywords"] == ["AI Agent", "实习"]
    assert state.plan == [
        "search_jobs",
        "analyze_job",
        "retrieve_resume",
        "rank_jobs",
        "create_campaign",
        "request_approval",
    ]
