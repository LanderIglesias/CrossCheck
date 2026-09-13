"""Phase 1: chunk + embed Pilgrim's Pride's (PPC) real 10-Q filing and store it in `chunks`.

Idempotent: re-running clears PPC's existing chunks first (ON CONFLICT would require matching
chunk_index across re-chunking runs, which isn't guaranteed if chunking parameters change).
"""

from __future__ import annotations

from pathlib import Path

from crosscheck.db import get_connection
from crosscheck.ingest.chunker import chunk_text
from crosscheck.ingest.filing_text import extract_text
from crosscheck.retrieval.embeddings import embed_texts

TICKER = "PPC"


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.id, d.local_path FROM documents d "
            "JOIN quarters q ON q.id = d.quarter_id "
            "JOIN companies co ON co.id = q.company_id "
            "WHERE co.ticker = %s AND d.modality = 'filing'",
            (TICKER,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"No filing document for {TICKER} — run `make seed` first")
        document_id, local_path = row

        html = Path(local_path).read_text(encoding="utf-8", errors="ignore")
        plaintext = extract_text(html)
        chunks = chunk_text(plaintext)
        print(f"Extracted {len(plaintext):,} chars of plaintext -> {len(chunks)} chunks")

        embeddings = embed_texts([c.text for c in chunks])
        print(f"Embedded {len(chunks)} chunks with bge-m3 (shape={embeddings.shape})")

        cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            cur.execute(
                """INSERT INTO chunks (document_id, chunk_index, char_start, char_end, text,
                                        embedding)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    document_id,
                    chunk.chunk_index,
                    chunk.char_start,
                    chunk.char_end,
                    chunk.text,
                    str(embedding.tolist()),
                ),
            )
        print(f"Stored {len(chunks)} chunks for {TICKER} (document_id={document_id})")


if __name__ == "__main__":
    main()
