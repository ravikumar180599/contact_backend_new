# sip_receiver/db.py
import os
import logging
from typing import Optional, Tuple

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
LOG.info("SIP Receiver DB pool ready %s:%s db=%s user=%s", PG_HOST, PG_PORT, PG_DB, PG_USER)


# ---- Helpers -----------------------------------------------------------------

def _getconn():
    return POOL.getconn()

def _putconn(conn):
    try:
        POOL.putconn(conn)
    except Exception:
        pass


# ---- Public API --------------------------------------------------------------

def get_ready_agent_and_assign(call_id: str) -> Optional[Tuple[str, str]]:
    """
    Atomically pick the OLDEST READY agent (by created_at), mark it INPROGRESS,
    set call_id, and return (agent_id, sock_url).

    Concurrency-safe using:
      ORDER BY created_at ASC
      FOR UPDATE SKIP LOCKED
      LIMIT 1

    Returns:
      (agent_id, sock_url) or None if no READY agent is available.
    """
    sql = """
    WITH picked AS (
        SELECT id
        FROM call_mapping
        WHERE agent_status = 'READY'
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE call_mapping c
    SET agent_status = 'INPROGRESS',
        call_id      = %s,
        updated_at   = now(),
        end_time     = NULL
    FROM picked
    WHERE c.id = picked.id
    RETURNING c.agent_id, c.sock_url;
    """
    conn = _getconn()
    try:
        with conn:  # transaction (commit/rollback)
            with conn.cursor() as cur:
                cur.execute(sql, (call_id,))
                row = cur.fetchone()
                if not row:
                    LOG.info("No READY agent available to assign call_id=%s", call_id)
                    return None
                agent_id = row["agent_id"]
                sock_url = row["sock_url"]
                LOG.info("Assigned call_id=%s to agent_id=%s (ws=%s)", call_id, agent_id, sock_url)
                return agent_id, sock_url
    finally:
        _putconn(conn)


def mark_call_completed(call_id: str) -> int:
    """
    Mark the row(s) for this call_id as COMPLETED, set end_time=now(), and bump updated_at.

    Returns:
      number of rows updated (int).
    """
    sql = """
    UPDATE call_mapping
    SET agent_status = 'COMPLETED',
        end_time     = now(),
        updated_at   = now()
    WHERE call_id = %s;
    """
    conn = _getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, (call_id,))
                updated = cur.rowcount or 0
                LOG.info("Marked call_id=%s as COMPLETED (rows=%s)", call_id, updated)
                return updated
    finally:
        _putconn(conn)
