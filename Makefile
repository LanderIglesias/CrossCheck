.PHONY: db-up db-down migrate seed label test lint

db-up:
	docker compose up -d

db-down:
	docker compose down

migrate:
	for f in db/migrations/*.sql; do psql "$$DATABASE_URL" -f "$$f"; done

# Re-run after `make test` — the DB migration test drops and recreates the schema, wiping seeded
# data. `seed` restores the 5 companies/quarters, re-populates the documents table (idempotent,
# re-downloads are cache-hits except audio/deck/filing which dedupe on content hash), re-inserts
# the hand-labeled Phase 0 gold set (claims + gold_labels), re-chunks+embeds PPC's filing for
# Phase 1 retrieval (downloads bge-m3 on first run, ~2.2GB, then reuses the local model cache),
# re-runs Phase 8's automated XBRL claim extraction for all 5 companies, and Phase 6's automated
# deck-PDF claim extraction for PPC.
seed:
	psql "$$DATABASE_URL" -f db/seed_companies.sql
	python scripts/populate_phase0_documents.py
	python scripts/populate_phase0_gold_labels.py
	python scripts/ingest_and_embed_filing.py
	python scripts/extract_xbrl_claims.py
	python scripts/extract_ppc_deck_claims.py

label:
	streamlit run src/crosscheck/labeling/app.py

test:
	pytest

lint:
	ruff check .
	black --check .
	mypy src scripts
	bandit -r src scripts
