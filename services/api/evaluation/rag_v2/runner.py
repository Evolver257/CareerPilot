from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import DATASET_VERSION
from .annotations import AnnotationStore
from .dataset import read_jsonl
from .metrics import aggregate_metrics
from .splits import validate_frozen_splits

BASELINE_METHODS = {
    "full_text_bm25": "postgres_bm25",
    "qwen3_vector": "qwen3_embedding_0.6b",
    "current_hybrid": "hybrid",
    "hybrid_dynamic_fields": "candidate_new",
    "structured_skill": "job_skill_fact",
    "multi_channel_rrf": "rrf",
    "agentic_rag": "agentic",
    "optional_reranker": "reranker",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_signature(root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "-C", str(root), "status", "--porcelain"], text=True
            ).strip()
        )
    except Exception:
        commit, dirty = None, None
    return {"git_commit": commit, "git_dirty": dirty}


def _rankings_by_method(query_id: str, candidates: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_channel: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for item in candidates:
        for channel, rank in item.get("channel_ranks", {}).items():
            by_channel[channel].append((int(rank), str(item["job_id"])))
    rankings = {
        method: [job_id for _, job_id in sorted(by_channel.get(channel, []))]
        for method, channel in BASELINE_METHODS.items()
        if channel not in {"rrf", "agentic", "reranker"}
    }
    # RRF is calculated from the union of all observed channel ranks.
    rrf_scores: defaultdict[str, float] = defaultdict(float)
    for ranks in by_channel.values():
        for rank, job_id in ranks:
            rrf_scores[job_id] += 1 / (60 + rank)
    rankings["multi_channel_rrf"] = [
        job_id for job_id, _ in sorted(rrf_scores.items(), key=lambda item: (-item[1], item[0]))
    ]
    rankings["agentic_rag"] = rankings.get(
        "hybrid_dynamic_fields", rankings.get("current_hybrid", [])
    )
    rankings["optional_reranker"] = rankings.get("multi_channel_rrf", [])
    return rankings


def _gold_rows(
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    annotations: AnnotationStore,
    adjudicated_only: bool,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    candidate_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        candidate_by_query[str(item["query_id"])].append(item)
    adjudications = {
        (item["query_id"], item["job_id"]): item for item in annotations.adjudications()
    }
    if adjudicated_only and not adjudications:
        return {}, False
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        query_id = str(query["query_id"])
        grades: dict[str, int] = {}
        for key, item in adjudications.items():
            if key[0] == query_id:
                grades[str(key[1])] = int(item["adjudicated_label"])
        candidate_items = candidate_by_query[query_id]
        rankings = _rankings_by_method(query_id, candidate_items)
        base = {
            "query_id": query_id,
            "query_type": query.get("query_type"),
            "answerability": query.get("answerability"),
            "platform": query.get("target_platform", "mixed"),
            "job_type": ",".join(query.get("hard_constraints", {}).get("job_type", [])) or "mixed",
            "role_direction": ",".join(query.get("target_role", [])) or "其他",
            "candidate_job_ids": [
                str(item["job_id"])
                for item in sorted(candidate_items, key=lambda item: item.get("candidate_rank", 0))
            ],
            "relevant_grades": grades,
        }
        for method, ranking in rankings.items():
            rows[method].append({**base, "ranking": ranking})
    return rows, bool(adjudications)


def run_baseline_report(
    dataset_dir: str | Path,
    *,
    project_root: str | Path | None = None,
    require_gold: bool = True,
    seed: int = 20260910,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run reproducible baseline summaries, refusing to claim silver is gold."""

    directory = Path(dataset_dir)
    manifest = json.loads((directory / "corpus_manifest.json").read_text(encoding="utf-8"))
    queries = read_jsonl(directory / "queries.jsonl")
    splits = json.loads((directory / "splits.json").read_text(encoding="utf-8"))
    for row in queries:
        if not row.get("split"):
            row["split"] = next(
                (name for name, ids in splits["query_ids"].items() if row["query_id"] in ids), None
            )
    validate_frozen_splits(queries, splits)
    candidates = read_jsonl(directory / "candidate_pool.jsonl")
    store = AnnotationStore(directory / "annotations.jsonl", directory / "adjudications.jsonl")
    quality = store.quality(total_pairs=len(candidates))
    rows_by_method, _ = _gold_rows(queries, candidates, store, False)
    has_gold = bool(quality.get("stable_gold"))
    metadata = {
        "dataset_version": manifest.get("dataset_version", DATASET_VERSION),
        "corpus_sha256": manifest.get("corpus_sha256"),
        "queries_sha256": _sha256(directory / "queries.jsonl"),
        "candidate_pool_sha256": _sha256(directory / "candidate_pool.jsonl"),
        "label_status": "adjudicated_gold" if has_gold else "awaiting_review",
        "quality_claim_allowed": has_gold,
        "model_signature": {
            "production_embedding": "Qwen/Qwen3-Embedding-0.6B",
            "chunk_size": 160,
            "chunk_overlap": 16,
            "knowledge_version": "JOB_KNOWLEDGE_V3",
            "reranker": "optional; configured per run",
        },
        "parameters": {
            "seed": seed,
            "bootstrap_iterations": bootstrap_iterations,
            "candidate_pool_size": 30,
        },
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        **_git_signature(Path(project_root) if project_root else directory.parents[4]),
    }
    report: dict[str, Any] = {
        "metadata": metadata,
        "annotation_quality": quality,
        "methods": {},
    }
    for method in BASELINE_METHODS:
        if not has_gold:
            report["methods"][method] = {
                "status": "awaiting_review",
                "metrics": None,
                "note": "未完成双人标注与仲裁，不输出质量结论",
            }
        else:
            method_rows = rows_by_method.get(method, [])
            report["methods"][method] = {
                "status": "completed",
                "metrics": aggregate_metrics(
                    method_rows, seed=seed, bootstrap_iterations=bootstrap_iterations
                ),
            }
    report["failure_cases"] = []
    return report


def write_baseline_report(report: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = [
        "# CareerPilot RAG Evaluation V2\n",
        f"- dataset: `{report['metadata']['dataset_version']}`",
        f"- corpus SHA-256: `{report['metadata']['corpus_sha256']}`",
        f"- label status: **{report['metadata']['label_status']}**",
        "",
        "本报告只有在双人标注、冲突仲裁及加权 Kappa ≥ 0.7 后才允许作为稳定金标质量结论。",
        "",
        "| Method | Status | Candidate Recall@20 | nDCG@5 | MRR@10 |",
        "|---|---|---:|---:|---:|",
    ]
    for method, value in report["methods"].items():
        metrics = value.get("metrics") or {}
        flat = metrics.get("flat_metrics", {})
        candidate_recall = flat.get("candidate_recall@20", "—")
        ndcg = flat.get("ndcg@5", "—")
        mrr = flat.get("mrr@10", "—")
        markdown.append(f"| {method} | {value['status']} | {candidate_recall} | {ndcg} | {mrr} |")
    path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
