from httpx import AsyncClient


async def test_health_checks_content_not_successful_run_history(client: AsyncClient):
    empty = await client.get("/api/knowledge/status")
    assert empty.status_code == 200
    assert empty.json()["ready"] is False
    assert empty.json()["latest_run"] is None
    await client.post("/api/knowledge/index-runs", json={"mode": "backfill", "auto_start": False})
    after_empty_backfill = (await client.get("/api/knowledge/status")).json()
    assert after_empty_backfill["latest_run"]["status"] == "SUCCEEDED"
    assert after_empty_backfill["ready"] is False
    assert after_empty_backfill["document_count"] == 0
    assert after_empty_backfill["chunk_count"] == 0
    assert "request" not in after_empty_backfill["latest_run"]


async def test_health_reports_unindexed_jobs_without_loading_run_history(client: AsyncClient):
    await client.post("/api/jobs", json={
        "title": "Health test engineer", "description": "Build Python systems.",
        "platform": "health-test", "external_job_id": "health-1",
    })
    health = (await client.get("/api/knowledge/status")).json()
    assert health["jobs_total"] == 1
    assert health["indexed_jobs"] == 0
    assert health["ready"] is False
    assert health["latest_run"]["status"] == "PENDING"
    assert "items" not in health
