import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection

from crosscheck.config import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_connection() -> Iterator[Connection]:
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        logger.exception("Rolling back transaction due to unhandled exception")
        conn.rollback()
        raise
    finally:
        conn.close()
