from __future__ import annotations


async def test_evaluation_seed_import_and_background_run(client) -> None:
    imported = await client.post("/api/evaluations/datasets/import-tool-seed")
    assert imported.status_code == 200
    dataset = imported.json()
    assert dataset["suite"] == "tool_calling"
    assert dataset["label_status"] == "seed_requires_dual_review"
    assert dataset["case_count"] > 0

    gold_rejected = await client.post(
        "/api/evaluations/runs",
        json={"dataset_id": dataset["id"], "require_gold": True},
    )
    assert gold_rejected.status_code == 422

    created = await client.post(
        "/api/evaluations/runs",
        json={"dataset_id": dataset["id"], "observations": []},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "PENDING"
    assert created.json()["progress_total"] == dataset["case_count"]

    cancelled = await client.post(
        f"/api/evaluations/runs/{created.json()['id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    retried = await client.post(f"/api/evaluations/runs/{created.json()['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "PENDING"


async def test_evaluation_rejects_sensitive_payload(client) -> None:
    response = await client.post(
        "/api/evaluations/datasets",
        json={
            "name": "unsafe",
            "suite": "answer",
            "version": "unsafe-v1",
            "label_status": "seed_requires_dual_review",
            "cases": [{"question": "password=secret"}],
        },
    )
    assert response.status_code == 422


async def test_answer_gold_requires_dual_annotation_and_adjudication(client) -> None:
    answer_case = {
        "case_id": "answer-001",
        "dataset_version": "v1",
        "split": "test",
        "category": "grounded_advice",
        "question": "北京 AI Agent 岗位需要哪些技能？",
        "answerable": True,
        "expected_refusal": False,
        "annotation_status": "seed_requires_dual_review",
    }
    rejected = await client.post(
        "/api/evaluations/datasets",
        json={
            "name": "invalid answer gold",
            "suite": "answer",
            "version": "answer-invalid-v1",
            "label_status": "adjudicated_gold",
            "cases": [answer_case],
        },
    )
    assert rejected.status_code == 422
    assert "not adjudicated gold" in rejected.json()["detail"]

    accepted = await client.post(
        "/api/evaluations/datasets",
        json={
            "name": "answer seed",
            "suite": "answer",
            "version": "answer-seed-v1",
            "label_status": "seed_requires_dual_review",
            "cases": [answer_case],
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["case_count"] == 1

    unknown = await client.post(
        "/api/evaluations/runs",
        json={
            "dataset_id": accepted.json()["id"],
            "observations": [{"case_id": "answer-unknown"}],
        },
    )
    assert unknown.status_code == 422
    assert "未知 case_id" in unknown.json()["detail"]
