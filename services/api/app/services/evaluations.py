from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.usage import UsageAccumulator
from app.models.entities import (
    AgentMemory,
    AgentMemorySetting,
    CareerAdvisorMessage,
    CareerAdvisorSession,
    EvaluationDataset,
    EvaluationRun,
    MemoryCandidate,
    User,
)
from app.models.work import BackgroundWork
from app.schemas.evaluations import EvaluationDatasetCreate, EvaluationRunCreate
from app.schemas.memory import MemoryCreate
from app.services.career_memory import CareerMemoryService
from app.services.llm_settings import LLMSettingsService
from app.services.work_queue import enqueue_work
from evaluation.answer_evaluation import evaluate_answer
from evaluation.memory_metrics import aggregate_memory_metrics, evaluate_memory_case
from evaluation.rag_ablation import (
    RAGAblationConfig,
    evaluate_recorded,
    summarize_recorded_rows,
)
from evaluation.schemas import (
    AnswerEvaluationCase,
    MemoryEvaluationCase,
    MemoryTaskObservation,
    RAGEvaluationCase,
    ToolEvaluationCase,
    ToolTaskObservation,
    assert_gold_ready,
)
from evaluation.tool_metrics import aggregate_tool_metrics, evaluate_tool_task


class EvaluationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_payload(value: Any) -> Any:
    raw = json.dumps(value, ensure_ascii=False)
    lowered = raw.casefold()
    has_credential = any(
        re.search(pattern, lowered)
        for pattern in (
            r"sk-[a-z0-9_-]{12,}",
            r"(?:api[_-]?key|password)\s*[:=]\s*[^\s,}\"]+",
            r"身份证(?:号|号码)?\s*[:：=]\s*\d{6,}",
        )
    )
    if has_credential:
        raise EvaluationError("评测数据疑似包含凭据或敏感身份信息")
    if len(raw.encode()) > 4_000_000:
        raise EvaluationError("评测数据超过 4 MB 限制")
    return json.loads(raw)


class EvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _validate_cases(self, payload: EvaluationDatasetCreate) -> list[dict[str, Any]]:
        safe_cases = _safe_payload(payload.cases)
        schema = {
            "tool_calling": ToolEvaluationCase,
            "rag_retrieval": RAGEvaluationCase,
            "answer": AnswerEvaluationCase,
            "memory": MemoryEvaluationCase,
        }[payload.suite]
        try:
            parsed = [schema.model_validate(item) for item in safe_cases]
        except Exception as exc:
            raise EvaluationError(f"评测数据集格式无效：{str(exc)[:500]}") from exc
        if payload.label_status == "adjudicated_gold":
            try:
                assert_gold_ready(parsed)
            except ValueError as exc:
                raise EvaluationError(str(exc)) from exc
        return [item.model_dump(mode="json") for item in parsed]

    async def create_dataset(self, payload: EvaluationDatasetCreate) -> EvaluationDataset:
        cases = self._validate_cases(payload)
        raw = json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()
        item = EvaluationDataset(
            name=payload.name,
            suite=payload.suite,
            version=payload.version,
            label_status=payload.label_status,
            sha256=hashlib.sha256(raw).hexdigest(),
            case_count=len(cases),
            cases=cases,
        )
        self.session.add(item)
        try:
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            raise EvaluationError("相同 suite/version 的数据集已存在") from exc
        return item

    async def import_tool_seed(self) -> EvaluationDataset:
        path = Path(__file__).parents[2] / "evaluation" / "datasets" / "tool_calls_seed_v1.jsonl"
        cases = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return await self.create_dataset(
            EvaluationDatasetCreate(
                name="Tool Calling 待标注种子集",
                suite="tool_calling",
                version="seed-v1",
                label_status="seed_requires_dual_review",
                cases=cases,
            )
        )

    async def import_memory_seed(self) -> EvaluationDataset:
        path = Path(__file__).parents[2] / "evaluation" / "datasets" / "memory_seed_v1.jsonl"
        cases = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return await self.create_dataset(
            EvaluationDatasetCreate(
                name="长期记忆待标注种子集",
                suite="memory",
                version="memory-seed-v1",
                label_status="seed_requires_dual_review",
                cases=cases,
            )
        )

    async def list_datasets(self) -> list[EvaluationDataset]:
        return list(
            (
                await self.session.scalars(
                    select(EvaluationDataset).order_by(EvaluationDataset.created_at.desc())
                )
            ).all()
        )

    async def get_dataset(self, dataset_id: UUID) -> EvaluationDataset:
        item = await self.session.get(EvaluationDataset, dataset_id)
        if item is None:
            raise EvaluationError("评测数据集不存在")
        return item

    async def create_run(self, payload: EvaluationRunCreate) -> EvaluationRun:
        dataset = await self.get_dataset(payload.dataset_id)
        if payload.require_gold and dataset.label_status != "adjudicated_gold":
            raise EvaluationError("该数据集尚未完成双人标注和仲裁，不能运行正式金标评测")
        observations = _safe_payload(payload.observations)
        case_ids = {str(item.get("case_id")) for item in dataset.cases}
        observation_ids = [str(item.get("case_id") or "") for item in observations]
        if any(not case_id for case_id in observation_ids):
            raise EvaluationError("每条 observation 都必须包含 case_id")
        if len(observation_ids) != len(set(observation_ids)):
            raise EvaluationError("observations 包含重复 case_id")
        unknown = sorted(set(observation_ids) - case_ids)
        if unknown:
            raise EvaluationError(f"observations 包含未知 case_id：{', '.join(unknown[:5])}")
        configuration = _safe_payload(payload.configuration)
        if dataset.suite == "rag_retrieval":
            allowed = {field.name for field in fields(RAGAblationConfig)}
            try:
                RAGAblationConfig(
                    **{key: value for key, value in configuration.items() if key in allowed}
                )
            except (TypeError, ValueError) as exc:
                raise EvaluationError(f"无效的 RAG 实验配置：{exc}") from exc
        item = EvaluationRun(
            dataset_id=dataset.id,
            status="PENDING",
            configuration={
                **configuration,
                "require_gold": payload.require_gold,
            },
            observations=observations,
            progress_total=dataset.case_count,
        )
        self.session.add(item)
        await self.session.flush()
        await enqueue_work(self.session, "evaluation", item.id)
        await self.session.commit()
        return item

    async def list_runs(self) -> list[EvaluationRun]:
        return list(
            (
                await self.session.scalars(
                    select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)
                )
            ).all()
        )

    async def get_run(self, run_id: UUID) -> EvaluationRun:
        item = await self.session.get(EvaluationRun, run_id)
        if item is None:
            raise EvaluationError("评测任务不存在")
        return item

    async def execute(self, run_id: UUID) -> EvaluationRun:
        run = await self.get_run(run_id)
        if run.status in {"SUCCEEDED", "CANCELLED"}:
            return run
        dataset = await self.get_dataset(run.dataset_id)
        run.status = "RUNNING"
        run.started_at = run.started_at or _now()
        run.error = None
        await self.session.commit()
        try:
            if dataset.suite == "tool_calling":
                cases = [ToolEvaluationCase.model_validate(item) for item in dataset.cases]
                observed = {
                    item.case_id: item
                    for item in [
                        ToolTaskObservation.model_validate(value)
                        for value in run.observations
                    ]
                }
                rows = []
                for index, case in enumerate(cases, start=1):
                    rows.append(
                        evaluate_tool_task(
                            case,
                            observed.get(
                                case.case_id,
                                ToolTaskObservation(
                                    case_id=case.case_id,
                                    error="missing_observation",
                                ),
                            ),
                        )
                    )
                    await self._checkpoint_cases(run, rows, index)
                result = {"summary": aggregate_tool_metrics(rows), "cases": rows}
            elif dataset.suite == "rag_retrieval":
                cases = [RAGEvaluationCase.model_validate(item) for item in dataset.cases]
                allowed = {field.name for field in fields(RAGAblationConfig)}
                config = RAGAblationConfig(
                    **{key: value for key, value in run.configuration.items() if key in allowed}
                )
                rows = []
                for index, case in enumerate(cases, start=1):
                    partial = evaluate_recorded([case], run.observations, config)
                    rows.extend(partial["cases"])
                    await self._checkpoint_cases(run, rows, index)
                result = summarize_recorded_rows(rows, config)
            elif dataset.suite == "memory":
                cases = [MemoryEvaluationCase.model_validate(item) for item in dataset.cases]
                if run.configuration.get("execution_mode") == "online":
                    result = await self._execute_online_memory(run, cases)
                else:
                    observed = {
                        item.case_id: item
                        for item in [
                            MemoryTaskObservation.model_validate(value)
                            for value in run.observations
                        ]
                    }
                    rows = []
                    for index, case in enumerate(cases, start=1):
                        rows.append(
                            evaluate_memory_case(
                                case,
                                observed.get(
                                    case.case_id,
                                    MemoryTaskObservation(
                                        case_id=case.case_id,
                                        error="missing_observation",
                                    ),
                                ),
                            )
                        )
                        await self._checkpoint_cases(run, rows, index)
                    result = {"summary": aggregate_memory_metrics(rows), "cases": rows}
            else:
                cases = [AnswerEvaluationCase.model_validate(item) for item in dataset.cases]
                observed = {
                    str(item.get("case_id")): item
                    for item in run.observations
                    if item.get("case_id")
                }
                rows = []
                for case in cases:
                    observation = observed.get(case.case_id)
                    if observation is None:
                        observation = {
                            "case_id": case.case_id,
                            "category": case.category,
                            "claims": [
                                {
                                    "support_status": "UNSUPPORTED",
                                    "requires_citation": True,
                                    "citation_ids": [],
                                }
                            ],
                            "citations": [],
                            "relevant": False,
                            "did_refuse": False,
                            "evaluation_error": "missing_observation",
                        }
                    row = evaluate_answer(
                        {
                            **observation,
                            "case_id": case.case_id,
                            "category": case.category,
                            "should_refuse": case.expected_refusal,
                        }
                    )
                    rows.append(row)
                    await self._checkpoint_cases(run, rows, len(rows))
                keys = set().union(*(row.keys() for row in rows)) if rows else set()
                result = {
                    "summary": {
                        key: mean(
                            float(row[key])
                            for row in rows
                            if key in row and isinstance(row[key], int | float)
                        )
                        for key in keys
                        if any(isinstance(row.get(key), int | float) for row in rows)
                    },
                    "cases": rows,
                }
            result["evaluation_metadata"] = {
                "dataset_version": dataset.version,
                "dataset_sha256": dataset.sha256,
                "label_status": dataset.label_status,
                "quality_claim_allowed": dataset.label_status == "adjudicated_gold",
                "configuration": run.configuration,
            }
            run.result = result
            run.progress_current = run.progress_total
            run.status = "SUCCEEDED"
            run.finished_at = _now()
        except Exception as exc:
            run.status = "FAILED"
            run.error = str(exc)[:1000]
            run.finished_at = _now()
        await self.session.commit()
        return run

    async def _checkpoint_cases(
        self,
        run: EvaluationRun,
        rows: list[dict[str, Any]],
        completed: int,
    ) -> None:
        if completed % 10 != 0 and completed != run.progress_total:
            return
        run.progress_current = completed
        run.result = {
            "cases": list(rows),
            "partial": completed < run.progress_total,
        }
        await self.session.commit()

    async def _execute_online_memory(
        self,
        run: EvaluationRun,
        cases: list[MemoryEvaluationCase],
    ) -> dict[str, Any]:
        """Execute memory extraction and retrieval in an isolated evaluation user.

        The evaluator never writes into the real default user. Optional
        ``bootstrap_memories`` entries may provide stable labels such as
        ``memory-python`` so retrieval cases can compare against deterministic
        identifiers without exposing production memory IDs.
        """

        evaluation_user = User(
            email=f"evaluation-memory-{run.id}@careerpilot.invalid",
            name="CareerPilot memory evaluation",
        )
        self.session.add(evaluation_user)
        await self.session.flush()
        memory_settings = AgentMemorySetting(
            user_id=evaluation_user.id,
            enabled=True,
            auto_save_non_sensitive=False,
            retention_days=30,
            allowed_types=[
                "USER_PROFILE",
                "CAREER_GOAL",
                "JOB_PREFERENCE",
                "SKILL_BACKGROUND",
                "LEARNING_PROGRESS",
                "CONVERSATION_SUMMARY",
                "USER_CONFIRMED_FACT",
            ],
            allow_session_summaries=False,
            allow_unconfirmed_context=True,
            memory_token_budget=700,
            extraction_confidence_threshold=0.75,
        )
        advisor_session = CareerAdvisorSession(
            user_id=evaluation_user.id,
            title=f"评测运行 {run.id}",
        )
        self.session.add_all([memory_settings, advisor_session])
        await self.session.flush()
        label_to_id: dict[str, str] = {}
        usage = UsageAccumulator()
        rows: list[dict[str, Any]] = []
        try:
            provider = await LLMSettingsService(self.session).get_runtime_provider()
            embedding_provider = await LLMSettingsService(
                self.session
            ).get_runtime_embedding_provider()
            memory_service = CareerMemoryService(
                self.session,
                embedding_provider=embedding_provider,
                llm_provider=provider,
            )
            bootstrap = run.configuration.get("bootstrap_memories", [])
            if isinstance(bootstrap, list):
                for raw in bootstrap[:100]:
                    if not isinstance(raw, dict):
                        continue
                    label = str(raw.get("id") or raw.get("memory_id") or "").strip()
                    if not label:
                        continue
                    payload = MemoryCreate.model_validate(
                        {
                            "memory_type": raw.get("memory_type", "USER_CONFIRMED_FACT"),
                            "content": raw.get("content", ""),
                            "memory_key": raw.get("memory_key") or label,
                            "source_quote": raw.get("source_quote") or raw.get("content", ""),
                            "pinned": True,
                            "extraction_method": "SYSTEM_DERIVED",
                        }
                    )
                    item = await memory_service.create(
                        payload,
                        user_id=evaluation_user.id,
                        provenance={"source": "evaluation_bootstrap", "label": label},
                        user_confirmed=True,
                    )
                    label_to_id[label] = str(item.id)

            for index, case in enumerate(cases, start=1):
                message = CareerAdvisorMessage(
                    session_id=advisor_session.id,
                    role="user",
                    content=case.user_query,
                )
                self.session.add(message)
                await self.session.flush()
                try:
                    candidates = await memory_service.capture_candidates(
                        evaluation_user.id,
                        advisor_session.id,
                        message.id,
                        case.user_query,
                    )
                    retrieved = await memory_service.retrieve(
                        evaluation_user.id,
                        case.user_query,
                        limit=case.retrieval_top_k,
                        allow_unconfirmed=True,
                    )
                    last_usage = getattr(provider, "last_usage", None)
                    usage.add(last_usage)
                    observation = MemoryTaskObservation(
                        case_id=case.case_id,
                        extracted_candidates=[
                            {
                                "memory_id": str(item.id),
                                "memory_type": item.memory_type,
                                "memory_key": item.memory_key,
                                "source_quote": item.source_quote or "",
                            }
                            for item in candidates
                        ],
                        retrieved_memory_ids=[
                            next(
                                (
                                    label
                                    for label, item_id in label_to_id.items()
                                    if item_id == str(item.id)
                                ),
                                str(item.id),
                            )
                            for item in retrieved
                        ],
                        sensitive_memory_saved=False,
                        task_completed=True,
                    )
                except Exception as exc:
                    observation = MemoryTaskObservation(
                        case_id=case.case_id,
                        task_completed=False,
                        error=str(exc)[:500],
                    )
                rows.append(evaluate_memory_case(case, observation))
                await self._checkpoint_cases(run, rows, index)
            return {
                "summary": aggregate_memory_metrics(rows),
                "cases": rows,
                "online_execution": {
                    "bootstrap_count": len(label_to_id),
                    "token_usage": usage.as_dict(),
                    "isolated_user": True,
                },
            }
        finally:
            await self.session.execute(
                delete(MemoryCandidate).where(MemoryCandidate.user_id == evaluation_user.id)
            )
            await self.session.execute(
                delete(AgentMemory).where(AgentMemory.user_id == evaluation_user.id)
            )
            await self.session.execute(
                delete(CareerAdvisorMessage).where(
                    CareerAdvisorMessage.session_id == advisor_session.id
                )
            )
            await self.session.execute(
                delete(CareerAdvisorSession).where(CareerAdvisorSession.id == advisor_session.id)
            )
            await self.session.execute(
                delete(AgentMemorySetting).where(AgentMemorySetting.user_id == evaluation_user.id)
            )
            await self.session.execute(delete(User).where(User.id == evaluation_user.id))
            await self.session.commit()

    async def cancel(self, run_id: UUID) -> EvaluationRun:
        run = await self.get_run(run_id)
        if run.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            run.status = "CANCELLED"
            run.finished_at = _now()
            work = await self.session.scalar(
                select(BackgroundWork).where(
                    BackgroundWork.kind == "evaluation", BackgroundWork.run_id == run.id
                )
            )
            if work:
                work.status = "CANCELLED"
            await self.session.commit()
        return run

    async def retry(self, run_id: UUID) -> EvaluationRun:
        run = await self.get_run(run_id)
        if run.status not in {"FAILED", "CANCELLED"}:
            raise EvaluationError("只有失败或已取消的评测可以重试")
        run.status = "PENDING"
        run.error = None
        run.finished_at = None
        run.progress_current = 0
        run.result = {}
        await enqueue_work(self.session, "evaluation", run.id, retry=True)
        await self.session.commit()
        return run
