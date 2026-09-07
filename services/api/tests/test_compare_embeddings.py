from evaluation.compare_embeddings import (
    SparseIndex,
    rank_job_ids,
    reciprocal_rank_fusion,
    tokenize,
)


def test_tokenize_keeps_technical_terms_and_chinese_bigrams():
    tokens = tokenize("Python + RAG 知识库")

    assert "python" in tokens
    assert "rag" in tokens
    assert "知识" in tokens


def test_sparse_index_scores_matching_document_higher():
    index = SparseIndex(["Python RAG 知识库", "Java 前端开发"])

    scores = index.score("Python RAG")

    assert scores[0] > scores[1]


def test_reciprocal_rank_fusion_preserves_cross_channel_candidates():
    assert reciprocal_rank_fusion(["a", "b"], ["b", "c"])[0] == "b"
    assert set(reciprocal_rank_fusion(["a"], ["b"])) == {"a", "b"}


def test_rank_job_ids_deduplicates_chunks_by_job():
    result = rank_job_ids(
        ["job-a", "job-a", "job-b"],
        [0.9, 0.8, 0.7],
        None,
        None,
        dense_top_k=3,
        sparse_top_k=3,
        rerank_pool=2,
        strategy="dense",
    )

    assert result == ["job-a", "job-b"]
