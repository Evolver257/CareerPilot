import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.entities import Job, JobSkill
from app.schemas.market_insights import MarketInsightLLMOutput, RoadmapAdjustment
from app.services.market_insights import (
    MARKET_INSIGHT_LLM_MAX_TOKENS,
    MarketInsightAggregator,
    MarketInsightService,
    _llm_digest,
)


def _job(index: int) -> Job:
    job = Job(
        id=uuid4(),
        platform="boss",
        external_job_id=f"insight-{index}",
        title="机器人控制算法实习生",
        description="负责机器人运动控制算法开发、仿真验证、模型训练和数据评估。",
        location="北京",
        salary_min=200 + index * 10,
        salary_max=250 + index * 10,
        job_type="Internship",
        education_requirement="本科及以上，硕士优先",
        experience_requirement="在校生/经验不限",
        raw_data={"salary_text": f"{200 + index * 10}-{250 + index * 10}元/天"},
        normalized_data={
            "structured_job": {
                "role_category": "机器人算法",
                "responsibilities": [
                    "负责机器人运动控制算法开发",
                    "在 MuJoCo 中进行仿真验证和模型评估",
                ],
            }
        },
        updated_at=datetime.now(UTC),
    )
    job.skills = [
        JobSkill(skill_name="Python", skill_type="required", importance=0.9),
        JobSkill(skill_name="MuJoCo", skill_type="required", importance=0.8),
        JobSkill(skill_name="PyTorch", skill_type="preferred", importance=0.6),
    ]
    return job


def test_market_insight_aggregates_salary_education_skills_and_roadmap() -> None:
    jobs = [(_job(index), 20.0 - index) for index in range(10)]

    result = MarketInsightAggregator().build("机器人控制算法", jobs)

    assert result.sample_count == 10
    assert result.confidence == "high"
    assert result.salary_bands[0].unit == "cny_day"
    assert result.salary_bands[0].sample_count == 10
    assert result.education_distribution[0].label == "本科及以上"
    assert result.experience_distribution[0].label == "应届/经验不限"
    assert result.skills[0].category == "core"
    assert len(result.learning_roadmap) == 5
    assert result.responsibility_themes
    assert len(result.source_jobs) == 10


@pytest.mark.asyncio
async def test_llm_enhancement_sends_compact_digest_and_merges_only_deltas() -> None:
    result = MarketInsightAggregator().build(
        "机器人控制算法", [(_job(index), 20.0 - index) for index in range(10)]
    )

    class CompactProvider:
        provider_name = "openai"
        prompts: list[str] = []
        token_limits: list[int | None] = []

        async def generate_structured(self, prompt, schema, *, model=None, max_tokens=None):
            self.prompts.append(prompt)
            self.token_limits.append(max_tokens)
            return MarketInsightLLMOutput(
                summary_markdown="# 精简市场结论",
                learning_priorities=["优先掌握控制基础"],
                roadmap_adjustments=[
                    RoadmapAdjustment(
                        weeks="第 3-5 周",
                        focus="增加控制器参数调优实验",
                        add_skills=["PID"],
                    )
                ],
            )

    provider = CompactProvider()
    enhanced = await MarketInsightService._enhance_with_llm(result, provider)
    serialized_digest = json.dumps(_llm_digest(result), ensure_ascii=False)

    assert str(result.source_jobs[0].id) not in serialized_digest
    assert "job_ids" not in serialized_digest
    assert len(serialized_digest) < 5000
    assert provider.token_limits == [MARKET_INSIGHT_LLM_MAX_TOKENS]
    assert "不展示推理过程" in provider.prompts[0]
    assert "优先掌握控制基础" in enhanced.summary_markdown
    adjusted = next(item for item in enhanced.learning_roadmap if item.weeks == "第 3-5 周")
    assert "增加控制器参数调优实验" in adjusted.objectives
    assert "PID" in adjusted.skills


@pytest.mark.asyncio
async def test_market_insight_report_crud(client, monkeypatch) -> None:
    scheduled: list = []
    monkeypatch.setattr(
        "app.api.market_insights.schedule_market_insight",
        lambda report_id: scheduled.append(report_id),
    )
    monkeypatch.setattr(
        "app.api.market_insights.stop_market_insight",
        lambda report_id: _noop(),
    )

    response = await client.post(
        "/api/market-insights",
        json={"query": "AI Agent RAG", "mode": "fast", "max_jobs": 50},
    )
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "PENDING"
    assert scheduled

    duplicate = await client.post(
        "/api/market-insights",
        json={"query": "AI Agent RAG", "mode": "fast", "max_jobs": 50},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == created["id"]
    assert duplicate.json()["cached"] is True
    assert len(scheduled) == 1

    listing = await client.get("/api/market-insights")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    cancelled = await client.post(f"/api/market-insights/{created['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    deleted = await client.delete(f"/api/market-insights/{created['id']}")
    assert deleted.status_code == 204


async def _noop() -> None:
    return None
