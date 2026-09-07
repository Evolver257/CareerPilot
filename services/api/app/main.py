import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agents,
    browser_tasks,
    campaigns,
    career_advisor,
    dashboard,
    evaluations,
    health,
    jobs,
    knowledge,
    llm,
    market_insights,
    mcp,
    memory,
    platforms,
    resumes,
)
from app.core.config import get_settings
from app.services.career_advisor import shutdown_career_advisor_tasks
from app.services.knowledge_indexing import (
    recover_interrupted_knowledge_indexes,
    run_knowledge_consistency_check,
    schedule_knowledge_index,
    shutdown_knowledge_index_tasks,
)
from app.services.market_insights import (
    recover_interrupted_market_insights,
    schedule_market_insight,
    shutdown_market_insight_tasks,
)
from app.services.ranking_runs import (
    recover_interrupted_ranking_runs,
    schedule_ranking_run,
    shutdown_ranking_tasks,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    knowledge_check = await run_knowledge_consistency_check()
    if knowledge_check.get("check_failed"):
        logging.getLogger("careerpilot.startup").warning(
            "knowledge_consistency_check_failed"
        )
    else:
        logging.getLogger("careerpilot.startup").info(
            "knowledge_consistency_check status=%s needs_update_jobs=%s",
            knowledge_check.get("status"),
            knowledge_check.get("needs_update_jobs", 0),
        )
    recovered_run_ids = await recover_interrupted_ranking_runs()
    for run_id in recovered_run_ids:
        schedule_ranking_run(run_id)
    recovered_report_ids = await recover_interrupted_market_insights()
    for report_id in recovered_report_ids:
        schedule_market_insight(report_id)
    recovered_knowledge_run_ids = await recover_interrupted_knowledge_indexes()
    for run_id in recovered_knowledge_run_ids:
        schedule_knowledge_index(run_id)
    try:
        yield
    finally:
        await shutdown_ranking_tasks()
        await shutdown_market_insight_tasks()
        await shutdown_knowledge_index_tasks()
        await shutdown_career_advisor_tasks()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
http_logger = logging.getLogger("careerpilot.http")
http_logger.setLevel(logging.INFO)
if not http_logger.handlers:
    http_handler = logging.StreamHandler()
    http_handler.setFormatter(logging.Formatter("%(message)s"))
    http_logger.addHandler(http_handler)
http_logger.propagate = False


@app.middleware("http")
async def structured_request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()
    context = {
        "request_id": request_id,
        "user_id": None,
        "agent_run_id": None,
        "campaign_id": None,
        "task_id": None,
        "tool_name": None,
    }
    path_parts = [part for part in request.url.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[:2] == ["api", "agent-runs"]:
        context["agent_run_id"] = path_parts[2]
    if len(path_parts) >= 3 and path_parts[:2] == ["api", "campaigns"]:
        context["campaign_id"] = path_parts[2]
    if len(path_parts) >= 3 and path_parts[:2] == ["api", "browser-tasks"]:
        context["task_id"] = path_parts[2]
    if "tools" in path_parts:
        tool_index = path_parts.index("tools")
        if len(path_parts) > tool_index + 1:
            context["tool_name"] = path_parts[tool_index + 1]
    try:
        response = await call_next(request)
    except Exception:
        context.update(
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }
        )
        http_logger.exception("http_request_failed %s", json.dumps(context, ensure_ascii=False))
        raise
    context.update(
        {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
    )
    http_logger.info("http_request %s", json.dumps(context, ensure_ascii=False))
    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(knowledge.router)
app.include_router(resumes.router)
app.include_router(campaigns.router)
app.include_router(campaigns.applications_router)
app.include_router(agents.router)
app.include_router(browser_tasks.router)
app.include_router(dashboard.router)
app.include_router(platforms.router)
app.include_router(llm.router)
app.include_router(market_insights.router)
app.include_router(career_advisor.router)
app.include_router(memory.router)
app.include_router(mcp.router)
app.include_router(evaluations.router)
