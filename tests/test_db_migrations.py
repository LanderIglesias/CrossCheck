from pathlib import Path

import psycopg
import pytest

from crosscheck.config import settings

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"
MIGRATION_SQLS = [p.read_text() for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]

EXPECTED_TABLES = {
    "companies",
    "quarters",
    "documents",
    "claims",
    "evidence_spans",
    "gold_labels",
    "chunks",
}


@pytest.fixture
def db_conn():
    try:
        conn = psycopg.connect(settings.database_url, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable; start it with `make db-up` to run this test.")
    yield conn
    conn.close()


def test_migration_creates_expected_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for migration_sql in MIGRATION_SQLS:
            cur.execute(migration_sql)
        db_conn.commit()

        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}

    assert EXPECTED_TABLES.issubset(tables)
