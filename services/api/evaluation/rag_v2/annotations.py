from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.annotation import annotation_quality, requires_adjudication, weighted_cohen_kappa

from .schemas import Adjudication, RAGAnnotation


class AnnotationStore:
    """Small atomic JSONL store for annotation pause/resume and export.

    The store is intentionally append-free at the logical level: each
    annotator/query/job key is upserted into a compact JSONL snapshot.  This
    keeps the format inspectable and makes interrupted browser sessions
    resumable without introducing a production schema migration.
    """

    _lock = threading.RLock()

    def __init__(
        self, annotation_path: str | Path, adjudication_path: str | Path | None = None
    ) -> None:
        self.annotation_path = Path(annotation_path)
        self.adjudication_path = Path(
            adjudication_path or self.annotation_path.with_name("adjudications.jsonl")
        )

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def annotations(self) -> list[dict[str, Any]]:
        return self._read(self.annotation_path)

    def adjudications(self) -> list[dict[str, Any]]:
        return self._read(self.adjudication_path)

    @staticmethod
    def key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(item.get("annotator_id", "")),
            str(item.get("query_id", "")),
            str(item.get("job_id", "")),
        )

    def _write(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        temp.write_text(body, encoding="utf-8")
        temp.replace(path)

    def upsert(self, annotation: RAGAnnotation | dict[str, Any]) -> dict[str, Any]:
        value = (
            annotation
            if isinstance(annotation, RAGAnnotation)
            else RAGAnnotation.model_validate(annotation)
        )
        row = value.model_dump(mode="json")
        row["annotation_id"] = row["annotation_id"] or "{}:{}:{}".format(
            row["annotator_id"], row["query_id"], row["job_id"]
        )
        row["updated_at"] = datetime.now(UTC).isoformat()
        with self._lock:
            rows = self.annotations()
            index = {self.key(item): position for position, item in enumerate(rows)}
            key = self.key(row)
            if key in index:
                rows[index[key]] = row
            else:
                rows.append(row)
            rows.sort(key=lambda item: self.key(item))
            self._write(self.annotation_path, rows)
        return row

    def get(self, annotator_id: str, query_id: str, job_id: str) -> dict[str, Any] | None:
        key = (annotator_id, query_id, job_id)
        return next((item for item in self.annotations() if self.key(item) == key), None)

    def progress(self, annotator_id: str, total_pairs: int) -> dict[str, int | float]:
        rows = [item for item in self.annotations() if item.get("annotator_id") == annotator_id]
        submitted = sum(item.get("status") == "submitted" for item in rows)
        return {
            "annotator_id": annotator_id,
            "submitted": submitted,
            "draft_or_skipped": len(rows) - submitted,
            "total_pairs": total_pairs,
            "percent": round(submitted / total_pairs * 100, 2) if total_pairs else 0.0,
        }

    def conflicts(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self.annotations():
            if row.get("status") == "submitted":
                grouped[(str(row.get("query_id")), str(row.get("job_id")))].append(row)
        adjudicated = {(row["query_id"], row["job_id"]): row for row in self.adjudications()}
        result = []
        for key, rows in grouped.items():
            if len(rows) < 2:
                continue
            rows = sorted(rows, key=lambda item: str(item.get("annotator_id")))
            left, right = rows[0], rows[1]
            if (
                requires_adjudication(
                    int(left["relevance_grade"]),
                    int(right["relevance_grade"]),
                    answerability_a=left.get("answerability_judgment"),
                    answerability_b=right.get("answerability_judgment"),
                    hard_constraint_a=left.get("hard_constraint_violation"),
                    hard_constraint_b=right.get("hard_constraint_violation"),
                )
                and key not in adjudicated
            ):
                result.append(
                    {
                        "query_id": key[0],
                        "job_id": key[1],
                        "annotator_a": left,
                        "annotator_b": right,
                    }
                )
        return result

    def adjudicate(self, adjudication: Adjudication | dict[str, Any]) -> dict[str, Any]:
        value = (
            adjudication
            if isinstance(adjudication, Adjudication)
            else Adjudication.model_validate(adjudication)
        )
        row = value.model_dump(mode="json")
        key = (row["query_id"], row["job_id"])
        with self._lock:
            submitted = {
                str(item.get("annotator_id")): int(item["relevance_grade"])
                for item in self.annotations()
                if item.get("query_id") == key[0]
                and item.get("job_id") == key[1]
                and item.get("status") == "submitted"
            }
            if row["annotator_a_id"] not in submitted or row["annotator_b_id"] not in submitted:
                raise ValueError("adjudication requires both submitted annotations")
            if (
                submitted[row["annotator_a_id"]] != row["annotator_a_label"]
                or submitted[row["annotator_b_id"]] != row["annotator_b_label"]
            ):
                raise ValueError("adjudication labels do not match the original annotations")
            rows = [
                item
                for item in self.adjudications()
                if (item.get("query_id"), item.get("job_id")) != key
            ]
            rows.append(row)
            rows.sort(key=lambda item: (str(item.get("query_id")), str(item.get("job_id"))))
            self._write(self.adjudication_path, rows)
        return row

    def quality(
        self, *, min_stable_kappa: float = 0.7, total_pairs: int | None = None
    ) -> dict[str, Any]:
        grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
        for row in self.annotations():
            if row.get("status") == "submitted":
                grouped[(str(row.get("query_id")), str(row.get("job_id")))][
                    str(row.get("annotator_id"))
                ] = int(row["relevance_grade"])
        pairs = [value for value in grouped.values() if len(value) >= 2]
        labels_a = [sorted(value.items())[0][1] for value in pairs]
        labels_b = [sorted(value.items())[1][1] for value in pairs]
        metrics = (
            annotation_quality(labels_a, labels_b)
            if pairs
            else {"agreement_rate": None, "cohen_kappa": None}
        )
        metrics["weighted_kappa"] = weighted_cohen_kappa(labels_a, labels_b) if pairs else None
        metrics.update(
            {
                "dual_annotated_pairs": len(pairs),
                "adjudicated_pairs": len(self.adjudications()),
                "conflict_pairs": len(self.conflicts()),
                "stable_gold": bool(
                    metrics["weighted_kappa"] is not None
                    and metrics["weighted_kappa"] >= min_stable_kappa
                    and not self.conflicts()
                    and (total_pairs is None or len(pairs) >= total_pairs)
                ),
            }
        )
        return metrics
