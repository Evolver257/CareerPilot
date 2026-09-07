"""Post-hoc diagnostics, never used for tuning: python -m evaluation.analyze."""

import argparse
import json
import random
import statistics
from pathlib import Path


def analyze(output):
    output = Path(output)
    rows = json.loads((output / "results.json").read_text(encoding="utf-8"))
    labels = json.loads((output / "labels.json").read_text(encoding="utf-8"))
    queries = {q["id"]: q for q in labels["questions"]}
    baseline = {r["case_id"]: r for r in rows if r["mode"] == "hash_hybrid"}
    comparison, by_variant = [], []
    for mode in sorted({r["mode"] for r in rows}):
        group = [
            r for r in rows if r["mode"] == mode and r["split"] == "test" and r["relevant_count"]
        ]
        for variant in ["literal", "paraphrase"]:
            subset = [r for r in group if r["variant"] == variant]
            if subset:
                by_variant.append(
                    {
                        "mode": mode,
                        "variant": variant,
                        "n": len(subset),
                        **{
                            metric: statistics.mean(r["metrics"][metric] for r in subset)
                            for metric in ["recall", "ndcg", "mrr"]
                        },
                    }
                )
        if mode == "hash_hybrid" or not group:
            continue
        pairs = [
            {
                "case_id": r["case_id"],
                "query": queries[r["case_id"]]["query"],
                "topic": queries[r["case_id"]]["topic"],
                "delta_ndcg": r["metrics"]["ndcg"] - baseline[r["case_id"]]["metrics"]["ndcg"],
                "baseline_job_ids": baseline[r["case_id"]]["job_ids"],
                "candidate_job_ids": r["job_ids"],
            }
            for r in group
        ]
        topics = sorted({p["topic"] for p in pairs})
        deltas = {t: [p["delta_ndcg"] for p in pairs if p["topic"] == t] for t in topics}
        rng = random.Random(42)
        boot = sorted(
            statistics.mean(d for t in rng.choices(topics, k=len(topics)) for d in deltas[t])
            for _ in range(2000)
        )
        ordered = sorted(pairs, key=lambda p: p["delta_ndcg"])
        comparison.append(
            {
                "mode": mode,
                "baseline": "hash_hybrid",
                "mean_ndcg_delta": statistics.mean(p["delta_ndcg"] for p in pairs),
                "topic_bootstrap_95ci": [boot[49], boot[1949]],
                "wins": sum(p["delta_ndcg"] > 1e-9 for p in pairs),
                "ties": sum(abs(p["delta_ndcg"]) <= 1e-9 for p in pairs),
                "losses": sum(p["delta_ndcg"] < -1e-9 for p in pairs),
                "worst_cases": ordered[:3],
                "best_cases": ordered[-3:],
            }
        )
    result = {
        "method": "paired topic bootstrap, 2000 samples, seed=42; diagnostic only",
        "by_variant": by_variant,
        "comparison": comparison,
    }
    (output / "analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="../../outputs/evaluation-v1")
    analyze(parser.parse_args().output)
