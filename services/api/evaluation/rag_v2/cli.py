from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .candidates import generate_candidate_pool
from .dataset import build_snapshot, write_snapshot
from .queries import read_queries, write_query_seed
from .runner import run_baseline_report, write_baseline_report
from .splits import write_splits


def fetch_jobs(api_base: str, *, page_size: int = 100) -> list[dict]:
    jobs: list[dict] = []
    with httpx.Client(base_url=api_base.rstrip("/"), timeout=60.0, trust_env=False) as client:
        page = 1
        total = None
        while total is None or len(jobs) < total:
            response = client.get("/api/jobs", params={"page": page, "page_size": page_size})
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            jobs.extend(items)
            total = int(payload.get("total", len(jobs)))
            if not items:
                break
            page += 1
    return jobs


def build_all(args: argparse.Namespace) -> None:
    directory = Path(args.output_dir).resolve()
    jobs = fetch_jobs(args.api)
    selected, manifest = build_snapshot(
        jobs, sample_size=args.sample_size, seed=args.seed, full=args.all
    )
    write_snapshot(selected, manifest, directory)
    write_query_seed(directory / "queries.jsonl")
    queries = read_queries(directory / "queries.jsonl")
    split_queries, _ = write_splits(queries, directory / "splits.json", seed=args.seed)
    directory.joinpath("queries.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in split_queries)
        + "\n",
        encoding="utf-8",
    )
    candidates = generate_candidate_pool(
        split_queries,
        [item.model_dump(mode="json") for item in selected],
        pool_size=args.pool_size,
        seed=args.seed,
    )
    (directory / "candidate_pool.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in candidates) + "\n",
        encoding="utf-8",
    )
    candidate_bytes = (directory / "candidate_pool.jsonl").read_bytes()
    (directory / "candidate_pool_manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": manifest["dataset_version"],
                "corpus_sha256": manifest["corpus_sha256"],
                "queries_sha256": hashlib.sha256(
                    (directory / "queries.jsonl").read_bytes()
                ).hexdigest(),
                "candidate_pool_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "generated_at": datetime.now(UTC).isoformat(),
                "pool_size": args.pool_size,
                "channels": [
                    "postgres_bm25",
                    "qwen3_embedding_0.6b",
                    "hybrid",
                    "job_skill_fact",
                    "exact_title_role",
                    "production_baseline",
                    "candidate_new",
                    "random",
                    "human_supplement",
                ],
                "label_scores_exposed_to_annotator": False,
                "retrieval_adapter_mode": (
                    "deterministic_local_fallback_when_channel_results_are_not_injected"
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name in ("annotations.jsonl", "adjudications.jsonl"):
        path = directory / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    report = run_baseline_report(
        directory, project_root=Path(__file__).parents[4], require_gold=True, seed=args.seed
    )
    write_baseline_report(report, directory / "baseline_report.json")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="CareerPilot RAG Evaluation Dataset V2")
    value.add_argument("--api", default="http://127.0.0.1:8010")
    value.add_argument("--output-dir", default=str(Path(__file__).parent / "datasets" / "rag_v2"))
    value.add_argument("--sample-size", type=int, default=400)
    value.add_argument("--pool-size", type=int, default=30)
    value.add_argument("--seed", type=int, default=20260910)
    value.add_argument("--all", action="store_true", help="保留全部有效去重岗位")
    value.add_argument("command", nargs="?", default="all", choices=("all", "snapshot"))
    return value


if __name__ == "__main__":
    options = parser().parse_args()
    if options.command == "all":
        build_all(options)
    else:
        jobs = fetch_jobs(options.api)
        selected, manifest = build_snapshot(
            jobs, sample_size=options.sample_size, seed=options.seed, full=options.all
        )
        write_snapshot(selected, manifest, options.output_dir)
