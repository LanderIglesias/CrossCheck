-- Phase 0 data-scouting result: 5 companies chosen because each has exactly one earnings call
-- in the public Earnings-21 corpus (Rev.com, CC-BY-SA), each is a US SEC filer with a matching
-- 10-Q for that same quarter, AND each has a confirmed real investor-deck PDF for that quarter
-- (verified by live browser navigation of the company's own IR site, not guessed). CIKs, filing
-- accession numbers, and deck URLs verified live on 2026-09-10 (see db/data_scouting.md for the
-- full verification trail, including: the original 3 candidates — HSY, ILMN, COP — that turned
-- out to have NO investor deck at all for their quarter (swapped for GE, TRV, ADTN); and AXP,
-- swapped for Pilgrim's Pride (PPC) after actually reading its Earnings-21 audio transcript and
-- discovering it was NOT American Express's earnings call at all, but an unrelated analyst
-- conference ("Future of Commerce Symposium") mislabeled in the corpus metadata.

INSERT INTO companies (ticker, cik, name) VALUES
    ('PPC',  '0000802481', 'Pilgrim''s Pride Corporation'),
    ('DHR',  '0000313616', 'Danaher Corp'),
    ('GE',   '0000040545', 'General Electric Company'),
    ('TRV',  '0000086312', 'Travelers Companies Inc'),
    ('ADTN', '0000926282', 'Adtran Holdings Inc');

INSERT INTO quarters (company_id, fiscal_year, fiscal_period, call_date)
SELECT id, 2020, 'Q3', NULL FROM companies WHERE ticker IN ('PPC', 'ADTN');

INSERT INTO quarters (company_id, fiscal_year, fiscal_period, call_date)
SELECT id, 2020, 'Q1', NULL FROM companies WHERE ticker IN ('DHR', 'GE');

INSERT INTO quarters (company_id, fiscal_year, fiscal_period, call_date)
SELECT id, 2020, 'Q2', NULL FROM companies WHERE ticker = 'TRV';

-- call_date left NULL: Earnings-21 metadata doesn't include the exact call date, only which
-- calendar quarter. The 10-Q report_date (below) is the reliable anchor instead.
