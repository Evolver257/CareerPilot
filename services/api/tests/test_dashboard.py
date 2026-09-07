from httpx import AsyncClient

from app.services.dashboard import DashboardService


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


async def test_dashboard_does_not_invent_conversion_rates_between_independent_counts() -> None:
    class NonMonotonicDashboardRepository:
        async def snapshot(self):
            return {
                "jobs_total": 10,
                "high_match_jobs": 1,
                "campaigns_total": 1,
                "campaign_candidates": 8,
                "application_status": {"QUEUED": 8},
                "agent_runs": [],
            }

    dashboard = await DashboardService(NonMonotonicDashboardRepository()).overview()
    queued = next(stage for stage in dashboard.funnel if stage.key == "queued")
    assert queued.count == 8
    assert queued.conversion_rate is None
    assert all(
        stage.conversion_rate is None
        for stage in dashboard.funnel
    )
