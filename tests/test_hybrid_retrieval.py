import numpy as np

from crosscheck.retrieval import hybrid


def test_reciprocal_rank_fusion_prefers_items_ranked_highly_in_both_lists():
    ranking_a = [1, 2, 3, 4]
    ranking_b = [2, 1, 4, 3]
    fused = hybrid.reciprocal_rank_fusion([ranking_a, ranking_b])
    # 1 and 2 are top-2 in both lists, so they should fuse to the top-2 positions (in some order)
    assert set(fused[:2]) == {1, 2}


def test_reciprocal_rank_fusion_is_stable_for_a_single_ranking():
    ranking = [5, 3, 1]
    assert hybrid.reciprocal_rank_fusion([ranking]) == ranking


def test_bm25_rank_prefers_lexical_match():
    chunk_ids = [1, 2, 3]
    chunk_texts = [
        "the weather today is sunny and warm",
        "net sales were three billion dollars this quarter",
        "employees enjoyed the company picnic",
    ]
    ranked = hybrid.bm25_rank("net sales quarter", chunk_ids, chunk_texts)
    assert ranked[0] == 2


def test_dense_rank_orders_by_cosine_similarity(monkeypatch):
    chunk_ids = [10, 20, 30]
    chunk_texts = ["a", "b", "c"]
    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
        ],
        dtype=np.float32,
    )
    monkeypatch.setattr(hybrid, "embed_query", lambda query: np.array([1.0, 0.0], dtype=np.float32))
    ranked = hybrid.dense_rank("irrelevant query text", chunk_ids, chunk_texts, embeddings)
    # chunk 10's embedding is identical to the query vector -> highest cosine similarity
    assert ranked[0] == 10
    # chunk 30's embedding is the exact opposite direction -> lowest similarity, ranked last
    assert ranked[-1] == 30
