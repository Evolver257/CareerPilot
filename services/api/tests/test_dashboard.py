from httpx import AsyncClient


async def test_dashboard_returns_product_metrics_and_safe_empty_states(
    client: AsyncClient,
) -> None:
    empty = await client.get("/api/dashboard")
    assert empty.status_code == 200
    payload = empty.json()
    assert payload["summary"]["jobs_total"] == 0
    assert payload["summary"]["applications_total"] == 0
    assert [stage["key"] for stage in payload["funnel"]] == [
        "discovered",
        "high_match",
        "approval",
        "queued",
        "submitted",
    ]
    assert payload["agent"]["retry_count"] == 0
    assert payload["token_usage"]["source"] == "not_recorded"

    created = await client.post(
        "/api/jobs",
        json={
            "platform": "dashboard-test",
            "external_job_id": "dashboard-001",
            "title": "Dashboard Agent Engineer",
            "description": "Build safe AI agent systems.",
            "location": "Remote",
        },
    )
    assert created.status_code == 201
    populated = await client.get("/api/dashboard")
    assert populated.status_code == 200
    assert populated.json()["summary"]["jobs_total"] == 1
    assert populated.json()["funnel"][0]["count"] == 1
