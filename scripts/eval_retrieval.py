"""Phase 1 retrieval eval: dense-only vs. hybrid vs. hybrid+reranked, over PPC's real 10-Q chunks.

Ground truth for each query is found mechanically (which chunk(s) contain the exact known figure
from Phase 0's hand-verified claims), not hand-picked — see the QUERIES table below.

Honest limitation: 4 queries is a small, illustrative proof-of-concept eval, not a statistically
robust benchmark. Report the numbers as measured; do not read more into small differences than
4 data points can support.
"""

from __future__ import annotations

import numpy as np

from crosscheck.db import get_connection
from crosscheck.retrieval.hybrid import dense_rank, hybrid_rank, rerank_top_k

# (query, exact substring that only the ground-truth chunk(s) should contain)
QUERIES: list[tuple[str, str]] = [
    ("What were Pilgrim's Pride's net sales for the third quarter of 2020?", "3,075,121"),
    ("What was Pilgrim's Pride's net income for the third quarter of 2020?", "33,446"),
    ("What was Pilgrim's Pride's diluted earnings per share for Q3 2020?", "0.14"),
    ("What was Pilgrim's Pride's gross profit for the third quarter of 2020?", "313,842"),
]


def load_chunks() -> tuple[list[int], list[str], np.ndarray]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.text, c.embedding FROM chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "JOIN quarters q ON q.id = d.quarter_id "
            "JOIN companies co ON co.id = q.company_id "
            "WHERE co.ticker = 'PPC' ORDER BY c.chunk_index"
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("No chunks found for PPC — run scripts/ingest_and_embed_filing.py first")
    chunk_ids = [r[0] for r in rows]
    chunk_texts = [r[1] for r in rows]
    embeddings = np.array(
        [[float(x) for x in r[2].strip("[]").split(",")] for r in rows], dtype=np.float32
    )
    return chunk_ids, chunk_texts, embeddings


def ground_truth_chunk_ids(needle: str, chunk_ids: list[int], chunk_texts: list[str]) -> set[int]:
    return {cid for cid, text in zip(chunk_ids, chunk_texts, strict=True) if needle in text}


def recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    return 1.0 if relevant & set(ranked[:k]) else 0.0


def ndcg_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    dcg = sum(1.0 / np.log2(i + 2) for i, cid in enumerate(ranked[:k]) if cid in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def main() -> None:
    chunk_ids, chunk_texts, embeddings = load_chunks()
    id_to_text = dict(zip(chunk_ids, chunk_texts, strict=True))

    results: dict[str, list[dict[str, float]]] = {"dense": [], "hybrid": [], "hybrid+rerank": []}

    for query, needle in QUERIES:
        relevant = ground_truth_chunk_ids(needle, chunk_ids, chunk_texts)
        if not relevant:
            print(f"WARNING: no chunk contains {needle!r} for query {query!r} — skipping")
            continue

        dense = dense_rank(query, chunk_ids, chunk_texts, embeddings)
        hybrid = hybrid_rank(query, chunk_ids, chunk_texts, embeddings)
        reranked = rerank_top_k(query, hybrid, id_to_text, top_k=10)

        for name, ranked in (("dense", dense), ("hybrid", hybrid), ("hybrid+rerank", reranked)):
            results[name].append(
                {
                    "recall@5": recall_at_k(ranked, relevant, 5),
                    "recall@10": recall_at_k(ranked, relevant, 10),
                    "ndcg@10": ndcg_at_k(ranked, relevant, 10),
                }
            )

    print(f"\n{len(QUERIES)}-query retrieval eval over PPC's 10-Q ({len(chunk_ids)} chunks)")
    print(f"{'variant':<16}{'recall@5':>10}{'recall@10':>11}{'ndcg@10':>10}")
    for name, rows in results.items():
        if not rows:
            continue
        avg_r5 = sum(r["recall@5"] for r in rows) / len(rows)
        avg_r10 = sum(r["recall@10"] for r in rows) / len(rows)
        avg_ndcg = sum(r["ndcg@10"] for r in rows) / len(rows)
        print(f"{name:<16}{avg_r5:>10.2f}{avg_r10:>11.2f}{avg_ndcg:>10.3f}")


if __name__ == "__main__":
    main()
