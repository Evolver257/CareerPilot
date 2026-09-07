from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import EvaluationDataset, EvaluationRun
from app.models.work import BackgroundWork
from app.schemas.evaluations import EvaluationDatasetCreate, EvaluationRunCreate
from app.services.work_queue import enqueue_work
from evaluation.answer_evaluation import evaluate_answer
from evaluation.rag_ablation import (
    RAGAblationConfig,
    evaluate_recorded,
    summarize_recorded_rows,
)
from evaluation.schemas import (
    AnswerEvaluationCase,
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
    if any(token in lowered for token in ("sk-", "api_key", "password", "身份证")):
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
