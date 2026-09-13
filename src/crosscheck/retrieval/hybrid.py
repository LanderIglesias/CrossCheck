"""Hybrid (dense + BM25) retrieval with reciprocal rank fusion, plus optional reranking.

Operates in-process over a document's full chunk set rather than issuing a pgvector ANN query —
at this vertical slice's scale (one filing, on the order of a few hundred chunks) an in-process
cosine-similarity scan and an in-process BM25 index are both fast and avoid needing psycopg's
pgvector type adapter wired up just for this. Revisit if/when this needs to scale across many
documents at once.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from crosscheck.retrieval.embeddings import embed_query
from crosscheck.retrieval.reranker import rerank as rerank_passages


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: int
    text: str
    score: float


def dense_rank(
    query: str, chunk_ids: list[int], chunk_texts: list[str], chunk_embeddings: np.ndarray
) -> list[int]:
    """Rank chunk_ids by cosine similarity of their embedding to the query's embedding."""
    query_vec = embed_query(query)
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    doc_norms = chunk_embeddings / (np.linalg.norm(chunk_embeddings, axis=1, keepdims=True) + 1e-12)
    similarities = doc_norms @ query_norm
    order = np.argsort(-similarities)
    return [chunk_ids[i] for i in order]


def bm25_rank(query: str, chunk_ids: list[int], chunk_texts: list[str]) -> list[int]:
    """Rank chunk_ids by BM25 lexical relevance to the query."""
    tokenized_corpus = [text.lower().split() for text in chunk_texts]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    order = np.argsort(-scores)
    return [chunk_ids[i] for i in order]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Fuse multiple rankings of the same chunk_ids via reciprocal rank fusion."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda cid: -scores[cid])


def hybrid_rank(
    query: str, chunk_ids: list[int], chunk_texts: list[str], chunk_embeddings: np.ndarray
) -> list[int]:
    """Dense + BM25 rankings fused via reciprocal rank fusion."""
    dense = dense_rank(query, chunk_ids, chunk_texts, chunk_embeddings)
    lexical = bm25_rank(query, chunk_ids, chunk_texts)
    return reciprocal_rank_fusion([dense, lexical])


def rerank_top_k(
    query: str, ranked_chunk_ids: list[int], id_to_text: dict[int, str], top_k: int = 10
) -> list[int]:
    """Rerank the top_k of an existing ranking with the cross-encoder reranker."""
    candidates = ranked_chunk_ids[:top_k]
    passages = [id_to_text[cid] for cid in candidates]
    scores = rerank_passages(query, passages)
    order = np.argsort(-np.asarray(scores))
    reranked = [candidates[i] for i in order]
    return reranked + ranked_chunk_ids[top_k:]
