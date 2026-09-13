-- CrossCheck Phase 0 schema.
-- See db/schema.md for field-by-field rationale and worked examples.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE companies (
    id          SERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL UNIQUE,
    cik         TEXT NOT NULL UNIQUE,  -- SEC Central Index Key, zero-padded to 10 digits
    name        TEXT NOT NULL
);

CREATE TABLE quarters (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    fiscal_year     INTEGER NOT NULL,
    fiscal_period   TEXT NOT NULL,  -- 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'FY'
    call_date       DATE,
    UNIQUE (company_id, fiscal_year, fiscal_period)
);

CREATE TYPE modality AS ENUM ('audio', 'deck', 'filing', 'xbrl');

CREATE TABLE documents (
    id              SERIAL PRIMARY KEY,
    quarter_id      INTEGER NOT NULL REFERENCES quarters(id),
    modality        modality NOT NULL,
    source_url      TEXT NOT NULL,
    content_hash    TEXT NOT NULL,  -- sha256 of the downloaded bytes; drives idempotent re-runs
    local_path      TEXT NOT NULL,
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (quarter_id, modality, content_hash)
);

CREATE TABLE claims (
    id                      SERIAL PRIMARY KEY,
    document_id             INTEGER NOT NULL REFERENCES documents(id),
    subject                 TEXT NOT NULL,   -- e.g. 'total revenue', 'gross margin', company/segment name
    metric                  TEXT NOT NULL,   -- as stated in the source, pre-normalization
    canonical_metric_key    TEXT NOT NULL,   -- normalized join key used for cross-modal linking
    period                  TEXT NOT NULL,   -- normalized, e.g. 'FY2024-Q3'
    value                   NUMERIC,
    unit                    TEXT,            -- e.g. 'USD', 'USD_millions', 'percent', 'bps'
    qualifier               TEXT,            -- e.g. 'adjusted', 'non-GAAP', 'constant currency'
    speaker                 TEXT,            -- audio claims only; NULL otherwise
    extraction_method       TEXT NOT NULL,   -- 'manual' for Phase 0 gold-set seeding; model name later
    model_id                TEXT,
    prompt_hash             TEXT,
    confidence              REAL,
    embedding               vector(1024),    -- populated starting Phase 1 (bge-m3); NULL for now
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_claims_canonical_metric_key ON claims (canonical_metric_key);
CREATE INDEX idx_claims_document_id ON claims (document_id);

CREATE TYPE span_type AS ENUM ('audio_ts', 'page_bbox', 'char_offset', 'xbrl_fact');

CREATE TABLE evidence_spans (
    id          SERIAL PRIMARY KEY,
    claim_id    INTEGER NOT NULL REFERENCES claims(id),
    span_type   span_type NOT NULL,
    span_json   JSONB NOT NULL  -- shape depends on span_type; see db/schema.md
);

CREATE INDEX idx_evidence_spans_claim_id ON evidence_spans (claim_id);

CREATE TYPE verdict AS ENUM ('consistent', 'discrepant', 'unsupported', 'ambiguous');

CREATE TABLE gold_labels (
    id          SERIAL PRIMARY KEY,
    claim_a_id  INTEGER NOT NULL REFERENCES claims(id),
    claim_b_id  INTEGER REFERENCES claims(id),  -- NULL when verdict = 'unsupported'
    verdict     verdict NOT NULL,
    rationale   TEXT NOT NULL,
    labeled_by  TEXT NOT NULL,
    labeled_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (claim_b_id IS NULL OR claim_b_id != claim_a_id)
);

CREATE INDEX idx_gold_labels_claim_a ON gold_labels (claim_a_id);
