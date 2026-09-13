from __future__ import annotations

import hashlib
import math
import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .schemas import CandidateJob

CHANNELS = (
    "postgres_bm25",
    "qwen3_embedding_0.6b",
    "hybrid",
    "job_skill_fact",
    "exact_title_role",
    "production_baseline",
    "candidate_new",
    "random",
    "human_supplement",
)


def _tokens(value: Any) -> set[str]:
    text = str(value or "").casefold()
    ascii_tokens = set(re.findall(r"[a-z][a-z0-9+#.-]{1,30}", text))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    return (
        ascii_tokens | set(chinese) | {"".join(chinese[i : i + 2]) for i in range(len(chinese) - 1)}
    )


def _text(job: Mapping[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in ("title", "company", "description", "location", "role_direction", "job_type")
    )


def _contains_term(text: str, term: Any) -> bool:
    value = str(term or "").strip()
    if not value:
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+#.-]*", value):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text, re.I))
    return value.casefold() in text.casefold()


def _hash_vector(value: str, dimensions: int = 32) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokens(value):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _lexical(query: Mapping[str, Any], job: Mapping[str, Any]) -> float:
    q_tokens = _tokens(
        " ".join(
            [
                str(query.get("query") or ""),
                *query.get("target_role", []),
                *query.get("target_skills", []),
            ]
        )
    )
    j_tokens = _tokens(_text(job))
    if not q_tokens or not j_tokens:
        return 0.0
    return len(q_tokens & j_tokens) / math.sqrt(len(q_tokens) * len(j_tokens))


def _exact(query: Mapping[str, Any], job: Mapping[str, Any]) -> float:
    title = str(job.get("title") or "").casefold()
    role_hits = sum(_contains_term(title, value) for value in query.get("target_role", []))
    skill_hits = sum(_contains_term(title, value) for value in query.get("target_skills", []))
    return float(role_hits * 2 + skill_hits)


def _skill(query: Mapping[str, Any], job: Mapping[str, Any]) -> float:
    text = _text(job).casefold()
    skills = [str(value).casefold() for value in query.get("target_skills", [])]
    return sum(_contains_term(text, skill) for skill in skills) / max(len(skills), 1)


def _job_type_match(query: Mapping[str, Any], job: Mapping[str, Any]) -> float:
    requested = query.get("hard_constraints", {}).get("job_type", [])
    if isinstance(requested, str):
        requested = [requested]
    return float(not requested or str(job.get("job_type")) in requested)


def _score_channel(
    query: Mapping[str, Any],
    job: Mapping[str, Any],
    channel: str,
    vector_cache: dict[str, list[float]],
) -> float:
    lexical = _lexical(query, job)
    exact = _exact(query, job)
    skill = _skill(query, job)
    if channel == "postgres_bm25":
        return lexical + exact * 0.08
    if channel == "qwen3_embedding_0.6b":
        vector_cache.setdefault(f"q:{query['query_id']}", _hash_vector(str(query.get("query"))))
        vector_cache.setdefault(f"j:{job['job_id']}", _hash_vector(_text(job)))
        return (
            _cosine(vector_cache[f"q:{query['query_id']}"], vector_cache[f"j:{job['job_id']}"]) + 1
        ) / 2
    if channel == "hybrid":
        return lexical * 0.55 + skill * 0.3 + min(exact / 4, 1) * 0.15
    if channel == "job_skill_fact":
        return skill + lexical * 0.1
    if channel == "exact_title_role":
        return exact + skill * 0.01
    if channel == "production_baseline":
        return lexical * 0.7 + exact * 0.05 + _job_type_match(query, job) * 0.05
    if channel == "candidate_new":
        return (
            lexical * 0.35
            + skill * 0.35
            + min(exact / 4, 1) * 0.2
            + _job_type_match(query, job) * 0.1
        )
    return 0.0


def _score_cached(
    query: Mapping[str, Any],
    job: Mapping[str, Any],
    channel: str,
    *,
    query_tokens: set[str],
    job_tokens: set[str],
    query_vector: list[float],
    job_vector: list[float],
) -> float:
    """Score one pair using features precomputed once per query/job."""

    lexical = (
        len(query_tokens & job_tokens) / math.sqrt(len(query_tokens) * len(job_tokens))
        if query_tokens and job_tokens
        else 0.0
    )
    title = str(job.get("title") or "").casefold()
    exact = sum(2 for value in query.get("target_role", []) if _contains_term(title, value))
    exact += sum(1 for value in query.get("target_skills", []) if _contains_term(title, value))
    text = _text(job).casefold()
    skills = [str(value).casefold() for value in query.get("target_skills", [])]
    skill = sum(_contains_term(text, value) for value in skills) / max(len(skills), 1)
    requested = query.get("hard_constraints", {}).get("job_type", [])
    if isinstance(requested, str):
        requested = [requested]
    job_type_match = float(not requested or str(job.get("job_type")) in requested)
    if channel == "postgres_bm25":
        return lexical + exact * 0.08
    if channel == "qwen3_embedding_0.6b":
        return (_cosine(query_vector, job_vector) + 1) / 2
    if channel == "hybrid":
        return lexical * 0.55 + skill * 0.3 + min(exact / 4, 1) * 0.15
    if channel == "job_skill_fact":
        return skill + lexical * 0.1
    if channel == "exact_title_role":
        return exact + skill * 0.01
    if channel == "production_baseline":
        return lexical * 0.7 + exact * 0.05 + job_type_match * 0.05
    if channel == "candidate_new":
        return lexical * 0.35 + skill * 0.35 + min(exact / 4, 1) * 0.2 + job_type_match * 0.1
    return 0.0


def _external_ranks(value: Sequence[Any]) -> list[tuple[str, float]]:
    result = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            job_id = str(item.get("job_id") or item.get("id") or "")
            score = float(item.get("score") or 0.0)
        else:
            job_id, score = str(item), 0.0
        if job_id:
            result.append((job_id, score if score else 1 / index))
    return result


def generate_candidate_pool(
    queries: Sequence[Mapping[str, Any]],
    corpus: Sequence[Mapping[str, Any]],
    *,
    pool_size: int = 30,
    seed: int = 20260910,
    channel_results: Mapping[str, Mapping[str, Sequence[Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Create a union candidate pool without using labels.

    ``channel_results`` lets production adapters inject real PostgreSQL/BM25,
    Qwen, hybrid, JobSkillFact, baseline and new-retriever results.  When it
    is absent, deterministic lexical/hash fallbacks make the artifact useful
    for local development while clearly retaining the channel provenance.
    """

    if not 20 <= pool_size <= 40:
        raise ValueError("pool_size must be between 20 and 40")
    jobs = {str(job["job_id"]): job for job in corpus}
    rng = random.Random(seed)
    job_cache = {
        job_id: {
            "text": _text(job),
            "tokens": _tokens(_text(job)),
            "vector": _hash_vector(_text(job)),
        }
        for job_id, job in jobs.items()
    }
    output: list[dict[str, Any]] = []
    channel_results = channel_results or {}
    for query in queries:
        per_channel: dict[str, list[tuple[str, float]]] = {}
        query_text = " ".join(
            [
                str(query.get("query") or ""),
                *query.get("target_role", []),
                *query.get("target_skills", []),
            ]
        )
        query_tokens = _tokens(query_text)
        query_vector = _hash_vector(str(query.get("query") or ""))
        for channel in CHANNELS:
            injected = channel_results.get(channel, {}).get(str(query["query_id"]))
            if injected is not None:
                per_channel[channel] = _external_ranks(injected)
                continue
            if channel in {"random", "human_supplement"}:
                ids = list(jobs)
                rng.shuffle(ids)
                per_channel[channel] = [
                    (job_id, 1 / (index + 1)) for index, job_id in enumerate(ids[:8])
                ]
                continue
            ranked = sorted(
                (
                    (
                        job_id,
                        _score_cached(
                            query,
                            job,
                            channel,
                            query_tokens=query_tokens,
                            job_tokens=job_cache[job_id]["tokens"],
                            query_vector=query_vector,
                            job_vector=job_cache[job_id]["vector"],
                        ),
                    )
                    for job_id, job in jobs.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )
            per_channel[channel] = ranked[: max(pool_size, 50)]

        candidates: set[str] = set()
        for ranks in per_channel.values():
            candidates.update(job_id for job_id, _ in ranks)
        aggregate: dict[str, float] = defaultdict(float)
        channel_ranks: dict[str, dict[str, int]] = defaultdict(dict)
        channel_scores: dict[str, dict[str, float]] = defaultdict(dict)
        for channel, ranks in per_channel.items():
            for rank, (job_id, score) in enumerate(ranks, start=1):
                channel_ranks[job_id][channel] = rank
                channel_scores[job_id][channel] = round(float(score), 8)
                aggregate[job_id] += 1 / (60 + rank)
        ordered = sorted(candidates, key=lambda job_id: (-aggregate[job_id], job_id))
        if len(ordered) < pool_size:
            fill = list(jobs)
            rng.shuffle(fill)
            ordered.extend(job_id for job_id in fill if job_id not in candidates)
        for rank, job_id in enumerate(ordered[:pool_size], start=1):
            output.append(
                CandidateJob(
                    query_id=str(query["query_id"]),
                    job_id=job_id,
                    candidate_rank=rank,
                    channels=sorted(channel_ranks[job_id]),
                    channel_ranks=dict(sorted(channel_ranks[job_id].items())),
                    channel_scores=dict(sorted(channel_scores[job_id].items())),
                ).model_dump(mode="json")
            )
    return output
