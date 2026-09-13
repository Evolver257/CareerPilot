from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import DATASET_VERSION
from .schemas import CorpusJob

ROLE_DIRECTIONS = (
    "AI Agent",
    "RAG",
    "后端",
    "前端",
    "算法",
    "产品",
    "测试",
    "数据",
    "机器人",
    "其他",
)

PLATFORM_NAMES = {"boss": "BOSS直聘", "zhipin": "BOSS直聘", "zhaopin": "智联招聘"}


def normalize_text(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value: Any) -> str:
    value = normalize_text(value).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value, flags=re.UNICODE)


def canonical_url(value: Any) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/"), "", "")
    )


def _nested(job: dict[str, Any], *path: str) -> Any:
    for root in (
        job,
        job.get("raw_data"),
        job.get("platform_metadata"),
        job.get("normalized_data"),
    ):
        value: Any = root
        if not isinstance(root, dict):
            continue
        for part in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, "", []):
            return value
    return None


def company_name(job: dict[str, Any]) -> str:
    for value in (
        job.get("company_name"),
        _nested(job, "raw_data", "company_name"),
        _nested(job, "normalized_data", "pipeline", "company"),
        _nested(job, "normalized_data", "structured_job", "company"),
    ):
        if value:
            return normalize_text(value)
    return ""


def city_name(location: Any) -> str:
    value = normalize_text(location)
    return re.split(r"[·,，/\s]", value, maxsplit=1)[0] if value else "unknown"


def normalize_job_type(job: dict[str, Any], title: str, description: str) -> str:
    value = normalize_text(
        job.get("job_type") or _nested(job, "normalized_data", "pipeline", "employment_type")
    )
    text = f"{title} {description} {value}"
    if re.search(r"实习|intern", text, re.I):
        return "实习"
    if re.search(r"校招|校园招聘|应届生招聘|管培生", text):
        return "校招"
    if value:
        return (
            "社招"
            if value.casefold()
            in {"full-time", "fulltime", "part-time", "contract", "全职", "兼职"}
            else value
        )
    return "社招"


def education_level(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return "unknown"
    if "博士" in text:
        return "博士"
    if "硕士" in text or "研究生" in text:
        return "硕士"
    if "本科" in text or "学士" in text:
        return "本科"
    if "大专" in text or "专科" in text:
        return "大专"
    if "学历不限" in text or "不限" in text:
        return "不限"
    return "其他"


def experience_level(value: Any, text: str = "") -> str:
    value = normalize_text(value)
    combined = f"{value} {text}"
    if re.search(r"经验不限|无经验|应届|在校", combined):
        return "不限/应届"
    match = re.search(r"(\d+)\s*[-~至]\s*(\d+)\s*年", combined)
    if match:
        return f"{match.group(1)}-{match.group(2)}年"
    match = re.search(r"(\d+)\s*年(?:以上)?", combined)
    if match:
        return f"{match.group(1)}年以上"
    return value or "unknown"


def classify_role(title: str, description: str) -> str:
    text = f"{title}\n{description}"
    # Specific families precede broad words such as AI and 安全.
    patterns = (
        ("AI Agent", r"Agent|智能体|工作流编排|工具调用|Function\s*Calling|MCP"),
        ("RAG", r"\bRAG\b|检索增强|向量数据库|知识库问答|Milvus|pgvector"),
        ("机器人", r"机器人|具身智能|运动控制|轨迹规划|ROS|无人机"),
        ("产品", r"产品经理|产品设计|产品运营|产品规划"),
        ("测试", r"测试开发|自动化测试|软件测试|质量保障"),
        (
            "前端",
            r"前端|(?<![A-Za-z])React(?![A-Za-z])|(?<![A-Za-z])Vue(?![A-Za-z])|Angular|JavaScript|TypeScript",
        ),
        ("后端", r"后端|服务端|Java\b|Spring|Go\b|Golang|FastAPI|微服务"),
        ("数据", r"数据分析|数据挖掘|数据工程|数仓|Spark|Flink|ETL"),
        ("算法", r"算法|机器学习|深度学习|NLP|自然语言|计算机视觉|模型训练|PyTorch"),
    )
    for direction, pattern in patterns:
        if re.search(pattern, text, re.I):
            return direction
    return "其他"


def _tokens(text: str) -> list[str]:
    ascii_tokens = re.findall(r"[a-z][a-z0-9+#.-]{1,30}", text.casefold())
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chinese[index : index + 2]) for index in range(max(0, len(chinese) - 1))]
    return ascii_tokens + chinese + bigrams


def simhash(text: str) -> int:
    bits = [0] * 64
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for index in range(64):
            bits[index] += 1 if value & (1 << index) else -1
    result = 0
    for index, value in enumerate(bits):
        if value >= 0:
            result |= 1 << index
    return result


def hamming_distance(left: int | str, right: int | str) -> int:
    if isinstance(left, str):
        left = int(left, 16)
    if isinstance(right, str):
        right = int(right, 16)
    return (left ^ right).bit_count()


def _similarity_tokens(left: str, right: str) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    return len(a & b) / len(a | b) if a and b else 0.0


def build_corpus_job(
    job: dict[str, Any], dataset_version: str = DATASET_VERSION
) -> CorpusJob | None:
    job_id = normalize_text(job.get("id"))
    title = normalize_text(job.get("title"))
    description = normalize_text(job.get("description"))
    if not job_id or not title or len(description) < 80:
        return None
    platform_key = normalize_key(job.get("platform"))
    platform = PLATFORM_NAMES.get(platform_key, normalize_text(job.get("platform")) or "unknown")
    company = company_name(job)
    location = normalize_text(job.get("location"))
    combined = f"{title}\n{description}"
    content_sha = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    fingerprint = simhash(combined)
    raw_edu = job.get("education_requirement") or _nested(
        job, "normalized_data", "pipeline", "education"
    )
    raw_exp = job.get("experience_requirement") or _nested(
        job, "normalized_data", "pipeline", "experience"
    )
    return CorpusJob(
        dataset_version=dataset_version,
        job_id=job_id,
        platform=platform,
        external_job_id=normalize_text(job.get("external_job_id")) or None,
        title=title,
        company=company,
        description=description,
        location=location,
        city=city_name(location),
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
        job_type=normalize_job_type(job, title, description),
        education_requirement=normalize_text(raw_edu),
        experience_requirement=normalize_text(raw_exp),
        education_level=education_level(raw_edu),
        experience_level=experience_level(raw_exp, combined),
        role_direction=classify_role(title, description),
        source_url=normalize_text(job.get("source_url")) or None,
        content_sha256=content_sha,
        jd_simhash=f"{fingerprint:016x}",
        dedup_keys={
            "platform_external_id": f"{platform}:{normalize_key(job.get('external_job_id'))}",
            "source_url": canonical_url(job.get("source_url")),
            "company_title": f"{normalize_key(company)}:{normalize_key(title)}",
        },
        normalized_fields={
            "platform_key": platform_key,
            "city": city_name(location),
            "role_direction": classify_role(title, description),
        },
    )


def _quality_key(item: CorpusJob) -> tuple[float, int, str]:
    return (
        float(item.normalized_fields.get("quality_score") or 0),
        len(item.description),
        item.job_id,
    )


def deduplicate_jobs(
    jobs: Iterable[dict[str, Any] | CorpusJob], *, dataset_version: str = DATASET_VERSION
) -> tuple[list[CorpusJob], dict[str, int]]:
    """Normalize and deduplicate without touching the production rows.

    Exact keys are evaluated first.  SimHash is only used as a conservative
    cross-platform near-duplicate check (distance <= 6 and token Jaccard >=
    .88), which avoids collapsing merely similar jobs such as React and ReAct.
    """

    normalized: list[CorpusJob] = []
    source_count = 0
    for raw in jobs:
        source_count += 1
        item = (
            raw
            if isinstance(raw, CorpusJob)
            else build_corpus_job(raw, dataset_version=dataset_version)
        )
        if item is not None:
            normalized.append(item)
    normalized.sort(key=lambda item: item.job_id)
    accepted: list[CorpusJob] = []
    exact: dict[str, CorpusJob] = {}
    simhash_items: list[tuple[int, CorpusJob]] = []
    duplicate_count = 0
    for item in normalized:
        keys = [
            item.dedup_keys.get("platform_external_id", ""),
            item.dedup_keys.get("source_url", ""),
            item.dedup_keys.get("company_title", ""),
            item.content_sha256,
        ]
        keys = [key for key in keys if key and not key.endswith(":")]
        duplicate = next((exact[key] for key in keys if key in exact), None)
        if duplicate is None:
            for previous_hash, previous in simhash_items:
                if (
                    hamming_distance(previous_hash, item.jd_simhash) <= 6
                    and _similarity_tokens(
                        previous.title + " " + previous.description,
                        item.title + " " + item.description,
                    )
                    >= 0.88
                ):
                    duplicate = previous
                    break
        if duplicate is not None:
            duplicate_count += 1
            continue
        accepted.append(item)
        simhash_items.append((int(item.jd_simhash, 16), item))
        for key in keys:
            exact[key] = item
    return accepted, {
        "source_job_count": source_count,
        "valid_job_count": len(normalized),
        "deduplicated_job_count": len(accepted),
        "duplicate_count": duplicate_count,
    }


def _dimension_value(item: CorpusJob, dimension: str) -> str:
    return str(getattr(item, dimension))


def stratified_sample(
    jobs: list[CorpusJob],
    sample_size: int = 400,
    seed: int = 20260910,
    full: bool = False,
) -> list[CorpusJob]:
    """Select a reproducible sample balancing platform, type, role, city and levels."""

    if full or sample_size >= len(jobs):
        return sorted(jobs, key=lambda item: item.job_id)
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    dimensions = (
        "platform",
        "job_type",
        "role_direction",
        "city",
        "education_level",
        "experience_level",
    )
    rng = random.Random(seed)
    shuffled = list(jobs)
    rng.shuffle(shuffled)
    rank = {item.job_id: index for index, item in enumerate(shuffled)}
    counts: dict[str, Counter[str]] = {dimension: Counter() for dimension in dimensions}
    totals: dict[str, Counter[str]] = {
        dimension: Counter(_dimension_value(item, dimension) for item in jobs)
        for dimension in dimensions
    }
    selected: list[CorpusJob] = []
    remaining = {item.job_id: item for item in jobs}
    for _ in range(min(sample_size, len(jobs))):

        def score(item: CorpusJob) -> tuple[float, float, int]:
            coverage = 0.0
            rarity = 0.0
            for dimension in dimensions:
                value = _dimension_value(item, dimension)
                observed = counts[dimension][value]
                target = sample_size * totals[dimension][value] / max(len(jobs), 1)
                coverage += max(0.0, target - observed) / max(target, 1.0)
                rarity += 1.0 / max(totals[dimension][value], 1)
            return coverage + rarity * 0.2, rng.random(), -rank[item.job_id]

        chosen = max(remaining.values(), key=score)
        selected.append(chosen)
        del remaining[chosen.job_id]
        for dimension in dimensions:
            counts[dimension][_dimension_value(chosen, dimension)] += 1
    return sorted(selected, key=lambda item: item.job_id)


def _distribution(items: Iterable[CorpusJob], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(item, field)) for item in items).items()))


def serialize_jsonl(items: Iterable[dict[str, Any] | CorpusJob]) -> bytes:
    rows = []
    for item in items:
        value = item.model_dump(mode="json") if isinstance(item, CorpusJob) else item
        rows.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return ("\n".join(rows) + "\n").encode("utf-8") if rows else b""


def build_snapshot(
    jobs: Iterable[dict[str, Any] | CorpusJob],
    *,
    sample_size: int = 400,
    seed: int = 20260910,
    full: bool = False,
    dataset_version: str = DATASET_VERSION,
) -> tuple[list[CorpusJob], dict[str, Any]]:
    raw_jobs = list(jobs)
    deduped, stats = deduplicate_jobs(raw_jobs, dataset_version=dataset_version)
    selected = stratified_sample(deduped, sample_size=sample_size, seed=seed, full=full)
    body = serialize_jsonl(selected)
    return selected, {
        "dataset_version": dataset_version,
        "corpus_sha256": hashlib.sha256(body).hexdigest(),
        "generated_at": datetime.now(UTC).isoformat(),
        **stats,
        "selected_job_count": len(selected),
        "sampling_seed": seed,
        "sampling_strategy": "all_valid_deduplicated"
        if full
        else "greedy_multidimensional_stratified",
        "platform_distribution": _distribution(selected, "platform"),
        "role_distribution": _distribution(selected, "role_direction"),
        "job_type_distribution": _distribution(selected, "job_type"),
        "city_distribution": _distribution(selected, "city"),
        "education_distribution": _distribution(selected, "education_level"),
        "experience_distribution": _distribution(selected, "experience_level"),
        "deduplication": {
            "keys": [
                "platform+external_job_id",
                "source_url",
                "normalized_company+title",
                "content_sha256",
                "jd_simhash",
            ],
            "simhash_hamming_threshold": 6,
            "simhash_token_jaccard_threshold": 0.88,
        },
    }


def write_snapshot(
    jobs: list[CorpusJob],
    manifest: dict[str, Any],
    output_dir: str | Path,
) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    body = serialize_jsonl(jobs)
    (path / "corpus.jsonl").write_bytes(body)
    manifest = {**manifest, "corpus_sha256": hashlib.sha256(body).hexdigest()}
    (path / "corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
