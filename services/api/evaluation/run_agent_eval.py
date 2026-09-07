"""Evaluate recorded Agent traces against a versioned tool-calling dataset.

Usage (from services/api):
  python -m evaluation.run_agent_eval --dataset evaluation/datasets/tool_calls_seed_v1.jsonl \
      --observations path/to/observations.jsonl --output ../../outputs/agent-evaluation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evaluation.schemas import ToolEvaluationCase, ToolTaskObservation, assert_gold_ready
from evaluation.tool_metrics import aggregate_tool_metrics, evaluate_tool_task


def _load_jsonl(path: Path, schema):
    values = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            values.append(schema.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"Invalid {path.name}:{line_number}: {exc}") from exc
    if not values:
        raise ValueError(f"{path} is empty")
    return values


def _git_metadata() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def run(
    dataset_path: Path, observations_path: Path, output_root: Path, *, require_gold: bool, seed: int
):
    started = datetime.now(UTC)
    cases = _load_jsonl(dataset_path, ToolEvaluationCase)
    observations = _load_jsonl(observations_path, ToolTaskObservation)
    if require_gold:
        assert_gold_ready(cases)
    case_by_id = {item.case_id: item for item in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("Duplicate case IDs in dataset")
    observation_by_id = {item.case_id: item for item in observations}
    if len(observation_by_id) != len(observations):
        raise ValueError("Duplicate case IDs in observations")
    unknown = sorted(set(observation_by_id) - set(case_by_id))
    if unknown:
        raise ValueError(f"Observations contain unknown cases: {', '.join(unknown[:5])}")

    # Missing observations are explicit failures, not silently excluded.
    results = []
    for case in cases:
        observation = observation_by_id.get(
            case.case_id,
            ToolTaskObservation(
                case_id=case.case_id,
                error="missing_observation",
            ),
        )
        results.append(evaluate_tool_task(case, observation))
    summary = aggregate_tool_metrics(results)
    finished = datetime.now(UTC)
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    run_id = started.strftime("%Y%m%dT%H%M%S.%fZ")
    output = output_root.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    commit, dirty = _git_metadata()
    label_statuses = sorted({item.annotation_status for item in cases})
    manifest = {
        "run_id": run_id,
        "suite": "agent_tool_calling",
        "dataset_version": sorted({item.dataset_version for item in cases}),
        "dataset_sha256": digest,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "git_commit": commit,
        "git_dirty": dirty,
        "seed": seed,
        "configuration": {"require_gold": require_gold},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "label_status": label_statuses,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "results.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in results),
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = [
        "# CareerPilot Agent Tool Calling Evaluation",
        "",
        f"- Run: `{run_id}`",
        f"- Dataset SHA-256: `{digest}`",
        f"- Label status: `{', '.join(label_statuses)}`",
        f"- Cases: {summary['cases']}",
        "",
        "|Metric|Value|",
        "|---|---:|",
    ]
    report.extend(
        f"|{key}|{value:.4f}|" if isinstance(value, float) else f"|{key}|{value}|"
        for key, value in summary.items()
        if key != "cases"
    )
    if not require_gold:
        report += [
            "",
            "> This is a harness/seed run, not a human-gold quality claim. Run with "
            "`--require-gold` after dual annotation and adjudication.",
        ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    return output, summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", default="../../outputs/agent-evaluation")
    parser.add_argument("--require-gold", action="store_true")
    parser.add_argument("--seed", type=int, default=20260907)
    arguments = parser.parse_args()
    destination, metrics = run(
        Path(arguments.dataset),
        Path(arguments.observations),
        Path(arguments.output),
        require_gold=arguments.require_gold,
        seed=arguments.seed,
    )
    print(json.dumps({"output": str(destination), "summary": metrics}, ensure_ascii=False))
