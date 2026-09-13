"""Thin wrapper around BAAI/bge-reranker-v2-m3 cross-encoder reranking."""

from __future__ import annotations

from typing import Any

_model: Any = None


def _get_model() -> Any:
    global _model
    if _model is None:
        from FlagEmbedding import FlagReranker

        _model = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=False, devices=["cpu"])
    return _model


def rerank(query: str, passages: list[str]) -> list[float]:
    """Score each passage's relevance to `query`. Higher is more relevant."""
    if not passages:
        return []
    model = _get_model()
    pairs = [[query, passage] for passage in passages]
    scores = model.compute_score(pairs, normalize=False)
    if isinstance(scores, float):
        scores = [scores]
    return [float(s) for s in scores]
