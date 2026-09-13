-- CrossCheck Phase 1: text chunking + dense retrieval.
-- Additive only — does not modify any Phase 0 table.

CREATE TABLE chunks (
    id            SERIAL PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id),
    chunk_index   INTEGER NOT NULL,       -- ordering within the document
    char_start    INTEGER NOT NULL,       -- offset into the cleaned plaintext; matches the
    char_end      INTEGER NOT NULL,       -- char_offset evidence_spans shape (db/schema.md)
    text          TEXT NOT NULL,
    embedding     vector(1024),           -- bge-m3 dense embedding; NULL until embedded
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_chunks_document_id ON chunks (document_id);

-- No HNSW index yet: pgvector builds it best over already-populated data, and this is a
-- single-document (PPC filing) vertical slice, small enough that a sequential scan over
-- cosine distance is fast without an ANN index. Added once real scale demands it.
