"""Thin wrapper around BAAI/bge-m3 dense embeddings.

Loads the real model on first call (lazily, so importing this module doesn't force a multi-GB
download just to run unrelated tests). CPU-only, per Phase 1's local/free constraint.
"""

from __future__ import annotations

from typing import Any

import numpy as np

_model: Any = None


def _get_model() -> Any:
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel

        _model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, devices=["cpu"])
    return _model


def embed_texts(texts: list[str], batch_size: int = 12) -> np.ndarray:
    """Embed a list of passages, returning an (N, 1024) float32 array of dense vectors."""
    model = _get_model()
    output = model.encode(
        texts,
        batch_size=batch_size,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    return np.asarray(output["dense_vecs"], dtype=np.float32)


def embed_query(query: str) -> np.ndarray:
    """Embed a single query, returning a (1024,) float32 vector."""
    return embed_texts([query])[0]
