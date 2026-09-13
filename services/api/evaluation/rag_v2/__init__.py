"""CareerPilot RAG Evaluation Dataset V2.

The package deliberately keeps the dataset builder separate from the V1
benchmark runner.  V2 data is versioned, JSONL based, and remains
``awaiting_review`` until two people have independently annotated every
query/job pair and conflicts have been adjudicated.
"""

DATASET_VERSION = "rag-v2.0.0"
METRICS_VERSION = "rag-v2-metrics-1"

__all__ = ["DATASET_VERSION", "METRICS_VERSION"]
