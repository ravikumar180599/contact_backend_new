# llm/db.py
import os
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

load_dotenv()

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---- Postgres connection pool ------------------------------------------------

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB   = os.getenv("PG_DATABASE", "postgres")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASSWORD", "postgres")

POOL_MIN = int(os.getenv("PG_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("PG_POOL_MAX", "10"))

POOL: SimpleConnectionPool = SimpleConnectionPool(
    POOL_MIN,
    POOL_MAX,
    host=PG_HOST,
    port=PG_PORT,
    dbname=PG_DB,
    user=PG_USER,
    password=PG_PASS,
    cursor_factory=RealDictCursor,
)
LOG.info("LLM DB pool ready %s:%s db=%s user=%s", PG_HOST, PG_PORT, PG_DB, PG_USER)


def _getconn():
    return POOL.getconn()


def _putconn(conn):
    try:
        POOL.putconn(conn)
    except Exception:
        pass


# ---- Public API --------------------------------------------------------------

def get_ws_url_for_call(call_id: str) -> Optional[str]:
    """
    Look up the WebSocket URL for a given call_id from call_mapping.
    Returns the most recently updated/created row's sock_url for that call_id.
    """
    if not call_id:
        return None

    sql = """
    SELECT sock_url
    FROM call_mapping
    WHERE call_id = %s
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1;
    """
    conn = _getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (call_id,))
            row = cur.fetchone()
            return row["sock_url"] if row and row.get("sock_url") else None
    except Exception:
        LOG.exception("DB error while fetching ws_url for call_id=%s", call_id)
        return None
    finally:
        _putconn(conn)