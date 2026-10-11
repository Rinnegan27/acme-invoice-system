"""Durable SQLite work queue with visibility timeout and DLQ."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from invoice_automation.adapters.sqlite_db import apply_schema, connect
from invoice_automation.domain.models import StageName


class SqliteWorkQueue:
    """SQLite-backed durable queue implementing WorkQueue Protocol."""

    def __init__(self, db_path: str | Path, schema_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._schema_path = Path(schema_path)
        with connect(self.db_path) as conn:
            apply_schema(conn, self._schema_path)

    def enqueue(
        self,
        stage: StageName,
        payload: dict[str, Any],
        idempotency_key: str,
        correlation_id: str,
    ) -> int:
        with connect(self.db_path) as conn:
            existing = conn.execute(
                """
                SELECT id FROM work_queue
                WHERE stage = ? AND idempotency_key = ?
                """,
                (stage.value, idempotency_key),
            ).fetchone()
            if existing:
                return int(existing["id"])

            processed = conn.execute(
                """
                SELECT 1 FROM processed_keys
                WHERE stage = ? AND idempotency_key = ?
                """,
                (stage.value, idempotency_key),
            ).fetchone()
            if processed:
                return -1

            cur = conn.execute(
                """
                INSERT INTO work_queue (stage, payload, idempotency_key, correlation_id)
                VALUES (?, ?, ?, ?)
                """,
                (stage.value, json.dumps(payload), idempotency_key, correlation_id),
            )
            conn.commit()
            return int(cur.lastrowid)

    def dequeue(
        self,
        stage: StageName,
        visibility_timeout_s: float = 30.0,
    ) -> dict[str, Any] | None:
        now = time.time()
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM work_queue
                WHERE stage = ? AND visible_at <= ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (stage.value, now),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE work_queue
                SET receive_count = receive_count + 1,
                    visible_at = ?
                WHERE id = ?
                """,
                (now + visibility_timeout_s, row["id"]),
            )
            conn.commit()
            return {
                "id": int(row["id"]),
                "stage": row["stage"],
                "payload": json.loads(row["payload"]),
                "idempotency_key": row["idempotency_key"],
                "correlation_id": row["correlation_id"],
                "receive_count": int(row["receive_count"]) + 1,
            }

    def ack(self, message_id: int) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT stage, idempotency_key, correlation_id FROM work_queue WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_keys (stage, idempotency_key, correlation_id)
                VALUES (?, ?, ?)
                """,
                (row["stage"], row["idempotency_key"], row["correlation_id"]),
            )
            conn.execute("DELETE FROM work_queue WHERE id = ?", (message_id,))
            conn.commit()

    def fail(self, message_id: int, reason: str, max_receive_count: int = 3) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return
            receive_count = int(row["receive_count"])
            if receive_count >= max_receive_count:
                payload = json.loads(row["payload"])
                invoice_id = str(payload.get("invoice_id", "unknown"))
                conn.execute(
                    """
                    INSERT INTO dlq (
                        original_id, stage, payload, idempotency_key, invoice_id,
                        correlation_id, receive_count, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["stage"],
                        row["payload"],
                        row["idempotency_key"],
                        invoice_id,
                        row["correlation_id"],
                        receive_count,
                        reason,
                    ),
                )
                conn.execute("DELETE FROM work_queue WHERE id = ?", (message_id,))
            else:
                # Make visible again immediately for retry.
                conn.execute(
                    "UPDATE work_queue SET visible_at = ? WHERE id = ?",
                    (time.time(), message_id),
                )
            conn.commit()

    def dlq_count(self) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM dlq").fetchone()
            return int(row["c"])

    def depth(self, stage: StageName | None = None) -> int:
        """Return pending work_queue depth (optionally for one stage)."""
        with connect(self.db_path) as conn:
            if stage is None:
                row = conn.execute("SELECT COUNT(*) AS c FROM work_queue").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM work_queue WHERE stage = ?",
                    (stage.value,),
                ).fetchone()
            return int(row["c"])

    def drop_correlation(self, stage: StageName, correlation_id: str) -> int:
        """Delete queued messages for a correlation (used when pausing after validate)."""
        with connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM work_queue WHERE stage = ? AND correlation_id = ?",
                (stage.value, correlation_id),
            )
            conn.commit()
            return int(cur.rowcount or 0)
