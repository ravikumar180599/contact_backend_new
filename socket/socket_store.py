# socket/socket_store.py
import os
import logging
from typing import Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from dotenv import load_dotenv
load_dotenv()

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class SocketStorePg:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        # Read defaults from environment (fall back to provided defaults)
        host = os.getenv("PG_HOST", host or "localhost")
        port = int(os.getenv("PG_PORT", port or 5432))
        user = os.getenv("PG_USER", user or "postgres")
        password = os.getenv("PG_PASSWORD", password or "postgres")
        database = os.getenv("PG_DATABASE", database or "test")

        LOG.info("Connecting to Postgres %s:%s db=%s user=%s", host, port, database, user)
        self.conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            cursor_factory=RealDictCursor,
        )
        # self.conn.autocommit = True  # optional

        self._ensure_table()

    def _ensure_table(self) -> None:
        """
        Create call_mapping table if it doesn't exist (UUID PK via pgcrypto).
        """
        create_ext = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"  # for gen_random_uuid()
        create_sql = """
        CREATE TABLE IF NOT EXISTS call_mapping (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_status TEXT DEFAULT 'READY',
            call_id TEXT DEFAULT NULL,
            agent_id TEXT DEFAULT NULL,
            sock_url TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            end_time TIMESTAMP DEFAULT NULL
        );
        """
        idxs_sql = [
            "CREATE INDEX IF NOT EXISTS idx_call_mapping_agent_id  ON call_mapping (agent_id);",
            "CREATE INDEX IF NOT EXISTS idx_call_mapping_call_id   ON call_mapping (call_id);",
            "CREATE INDEX IF NOT EXISTS idx_call_mapping_updated_at ON call_mapping (updated_at);",
            "CREATE INDEX IF NOT EXISTS idx_call_mapping_created_at ON call_mapping (created_at);",
        ]
        with self.conn.cursor() as cur:
            cur.execute(create_ext)
            cur.execute(create_sql)
            for stmt in idxs_sql:
                cur.execute(stmt)
        self.conn.commit()
        LOG.info("Ensured call_mapping table exists with UUID id")

    # ---------- convenience helpers ----------

    @staticmethod
    def _parse_ws_url(ws_url: str) -> Tuple[str, int]:
        # expects "ws://host:port"
        parts = ws_url.split(":")
        host = parts[1][2:]  # strip leading "//"
        port = int(parts[2])
        return host, port

    # ---------- public API ----------

    def add(self, agent_id: str, host: str, port: int) -> None:
        """
        Insert a NEW mapping row for this agent_id -> ws://host:port.
        (No upsert: agent_id is not unique by design.)
        """
        sock_url = f"ws://{host}:{port}"
        insert_sql = """
        INSERT INTO call_mapping (agent_status, call_id, agent_id, sock_url, created_at, updated_at)
        VALUES ('READY', NULL, %s, %s, now(), now());
        """
        with self.conn.cursor() as cur:
            cur.execute(insert_sql, (agent_id, sock_url))
        self.conn.commit()
        LOG.info("Inserted mapping: agent_id=%s -> %s", agent_id, sock_url)

    def add_url(self, agent_id: str, ws_url: str) -> None:
        """
        Convenience: same as add(), but takes a full ws:// URL.
        """
        host, port = self._parse_ws_url(ws_url)
        self.add(agent_id, host, port)

    def get(self, key: str) -> Optional[str]:
        """
        Return the most recent sock_url for the provided key.
        'key' may be an agent_id OR a call_id.

        Behavior tweak:
        - If 'key' matches agent_id, we FIRST try to find a row with agent_status='READY'
          so a READY agent always reuses the SAME ws URL.
        - If none is READY, we fall back to the most recent row for that agent_id (any status).
        - If still not found, we try call_id as before.
        """
        q_agent_ready = """
        SELECT sock_url FROM call_mapping
        WHERE agent_id = %s AND agent_status = 'READY'
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1;
        """
        q_agent_any = """
        SELECT sock_url FROM call_mapping
        WHERE agent_id = %s
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1;
        """
        q_call = """
        SELECT sock_url FROM call_mapping
        WHERE call_id = %s
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1;
        """
        with self.conn.cursor() as cur:
            # Prefer READY row for this agent
            cur.execute(q_agent_ready, (key,))
            row = cur.fetchone()
            if row and row.get("sock_url"):
                return row["sock_url"]

            # Fallback: any latest row for this agent
            cur.execute(q_agent_any, (key,))
            row = cur.fetchone()
            if row and row.get("sock_url"):
                return row["sock_url"]

            # Final attempt: look up by call_id
            cur.execute(q_call, (key,))
            row = cur.fetchone()
            if row and row.get("sock_url"):
                return row["sock_url"]

        return None

    def get_latest_for_agent(self, agent_id: str) -> Optional[tuple[str, str]]:
        """
        Return (agent_status, sock_url) for the LATEST row by created_at for this agent_id.
        Used by /init logic to decide whether to reuse the same ws URL (READY/INPROGRESS)
        or to allocate a new one when status is COMPLETED.
        """
        sql = """
        SELECT agent_status, sock_url
        FROM call_mapping
        WHERE agent_id = %s
        ORDER BY created_at DESC, updated_at DESC
        LIMIT 1;
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (agent_id,))
            row = cur.fetchone()
            if not row:
                return None
            return row["agent_status"], row["sock_url"]


    def close_open_ws(self, key: str) -> Optional[str]:
        """
        Delete the MOST RECENT mapping row (by updated_at, then created_at) for this key
        (agent_id or call_id) and return its sock_url. Leaves older rows intact.
        """
        sql = """
        WITH latest AS (
            SELECT id
            FROM call_mapping
            WHERE agent_id = %s OR call_id = %s
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
        )
        DELETE FROM call_mapping
        WHERE id IN (SELECT id FROM latest)
        RETURNING sock_url;
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (key, key))
            row = cur.fetchone()
        self.conn.commit()
        if row and row.get("sock_url"):
            LOG.info("Removed latest mapping for key=%s -> %s", key, row["sock_url"])
            return row["sock_url"]
        LOG.warning("No mapping found to remove for key=%s", key)
        return None

    def close(self) -> None:
        """Close DB connection."""
        try:
            self.conn.close()
            LOG.info("Postgres connection closed")
        except Exception:
            LOG.exception("Error while closing Postgres connection")
