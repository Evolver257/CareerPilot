from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def assign_splits(
    queries: list[dict[str, Any]],
    *,
    seed: int = 20260910,
    ratios: tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assign whole template groups to train/dev/test deterministically."""

    if len(ratios) != 3 or abs(sum(ratios) - 1) > 1e-8:
        raise ValueError("ratios must contain train/dev/test values summing to 1")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        group = str(
            query.get("template_group") or query.get("source_query_id") or query["query_id"]
        )
        groups[group].append(query)
    rng = random.Random(seed)
    group_items = list(groups.items())
    rng.shuffle(group_items)
    targets = [len(queries) * ratio for ratio in ratios]
    counts = [0, 0, 0]
    names = ("train", "dev", "test")
    assignment: dict[str, str] = {}
    for group, members in sorted(group_items, key=lambda item: (-len(item[1]), item[0])):
        eligible = [index for index in range(3) if counts[index] < targets[index] or index == 2]
        index = max(
            eligible,
            key=lambda value: (max(0.0, targets[value] - counts[value]), -counts[value], -value),
        )
        assignment[group] = names[index]
        counts[index] += len(members)
    stamped = []
    for query in queries:
        value = dict(query)
        value["split"] = assignment[
            str(query.get("template_group") or query.get("source_query_id") or query["query_id"])
        ]
        stamped.append(value)
    split_queries = {
        name: [item["query_id"] for item in stamped if item["split"] == name] for name in names
    }
    manifest = {
        "dataset_version": stamped[0].get("dataset_version", "rag-v2.0.0")
        if stamped
        else "rag-v2.0.0",
        "split_seed": seed,
        "split_strategy": "grouped_template_and_source_query; no group crosses split",
        "ratios": {name: ratio for name, ratio in zip(names, ratios, strict=True)},
        "counts": {name: len(split_queries[name]) for name in names},
        "query_ids": split_queries,
        "template_groups": {
            name: sorted(group for group, split in assignment.items() if split == name)
            for name in names
        },
        "test_frozen": True,
        "test_frozen_at": datetime.now(UTC).isoformat(),
    }
    return stamped, manifest


def write_splits(
    queries: list[dict[str, Any]], output_path: str | Path, seed: int = 20260910
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stamped, manifest = assign_splits(queries, seed=seed)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return stamped, manifest


def validate_frozen_splits(queries: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    if not manifest.get("test_frozen"):
        raise ValueError("test split is not frozen")
    expected = {query["query_id"]: query["split"] for query in queries}
    actual = {
        query_id: split for split, ids in manifest.get("query_ids", {}).items() for query_id in ids
    }
    if expected != actual:
        raise ValueError("query split assignments do not match frozen manifest")
    groups: dict[str, str] = {}
    for query in queries:
        group = query.get("template_group") or query["query_id"]
        previous = groups.setdefault(group, query["split"])
        if previous != query["split"]:
            raise ValueError(f"template group crosses splits: {group}")
