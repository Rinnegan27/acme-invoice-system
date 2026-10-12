"""SQLite persistence for the AP workbench (inbox / VP queue / history)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoice_automation.adapters.sqlite_db import connect
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem

CONFIDENCE_OVERRIDE_THRESHOLD = 0.80

SCHEMA = """
CREATE TABLE IF NOT EXISTS workbench_invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id  TEXT    NOT NULL UNIQUE,
    source_path     TEXT    NOT NULL,
    invoice_id      TEXT    NOT NULL,
    vendor          TEXT    NOT NULL,
    amount          TEXT    NOT NULL,
    due_date        TEXT,
    status          TEXT    NOT NULL,
    high_value      INTEGER NOT NULL DEFAULT 0,
    escalated       INTEGER NOT NULL DEFAULT 0,
    hard_blocked    INTEGER NOT NULL DEFAULT 0,
    confidence      REAL    NOT NULL DEFAULT 1.0,
    self_corrected  INTEGER NOT NULL DEFAULT 0,
    issues_json     TEXT    NOT NULL DEFAULT '[]',
    items_json      TEXT    NOT NULL DEFAULT '[]',
    raw_text        TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    analyst_notes   TEXT    NOT NULL DEFAULT '',
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS workbench_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id  TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    actor_role      TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL DEFAULT '{}',
    created_at      REAL    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workbench_source_path
    ON workbench_invoices (source_path);
"""


@dataclass
class WorkbenchRecord:
    """Mutable workbench row for UI lists and detail."""

    id: int
    correlation_id: str
    source_path: str
    invoice_id: str
    vendor: str
    amount: Decimal
    due_date: date | None
    status: str
    high_value: bool
    escalated: bool
    hard_blocked: bool
    confidence: float
    self_corrected: bool
    issues: list[str]
    items: list[dict[str, Any]]
    raw_text: str
    notes: str
    analyst_notes: str
    created_at: float
    updated_at: float

    @property
    def needs_override(self) -> bool:
        return self.confidence < CONFIDENCE_OVERRIDE_THRESHOLD or self.self_corrected

    @property
    def badges(self) -> list[str]:
        out: list[str] = []
        if self.high_value:
            out.append("HIGH VALUE")
        if self.escalated:
            out.append("ESCALATED")
        if self.hard_blocked:
            out.append("BLOCKED")
        elif self.issues:
            out.append("EXCEPTION")
        if self.needs_override and self.status not in {"paid", "rejected"}:
            out.append("LOW CONFIDENCE")
        return out

    @property
    def age_hours(self) -> float:
        return max(0.0, (time.time() - self.created_at) / 3600.0)

    def to_invoice(self) -> Invoice:
        items = tuple(
            LineItem(
                sku=str(i["sku"]),
                quantity=int(i["quantity"]),
                unit_price=Decimal(str(i["unit_price"]))
                if i.get("unit_price") is not None
                else None,
            )
            for i in self.items
        )
        status = InvoiceStatus.VALIDATED
        if self.status == "paid":
            status = InvoiceStatus.PAID
        elif self.status == "rejected":
            status = InvoiceStatus.REJECTED
        elif self.issues:
            status = InvoiceStatus.REJECTED
        return Invoice(
            invoice_id=self.invoice_id,
            vendor=self.vendor,
            amount=self.amount,
            due_date=self.due_date,
            items=items,
            source_path=self.source_path,
            status=status,
            issues=tuple(self.issues),
            correlation_id=self.correlation_id,
            approval_reason=self.notes,
        )


class WorkbenchStore:
    """CRUD for workbench invoices."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def get_by_source_path(self, source_path: str) -> WorkbenchRecord | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workbench_invoices WHERE source_path = ?",
                (str(Path(source_path).resolve()),),
            ).fetchone()
        return _row_to_record(row) if row else None

    def clear_all(self) -> None:
        """Delete all workbench rows and events (demo reset)."""
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM workbench_events")
            conn.execute("DELETE FROM workbench_invoices")
            conn.commit()

    def upsert_from_draft(
        self,
        *,
        correlation_id: str,
        source_path: str,
        invoice: Invoice,
        issues: tuple[str, ...],
        confidence: float,
        self_corrected: bool,
        raw_text: str,
        notes: str = "",
        hard_blocked: bool = False,
    ) -> WorkbenchRecord:
        now = time.time()
        source_path = str(Path(source_path).resolve())
        status = _initial_status(confidence, self_corrected, hard_blocked, issues, invoice)
        items = [
            {
                "sku": i.sku,
                "quantity": i.quantity,
                "unit_price": str(i.unit_price) if i.unit_price is not None else None,
            }
            for i in invoice.items
        ]
        with connect(self.db_path) as conn:
            # Idempotent on source file path so re-running Capture does not duplicate rows.
            existing = conn.execute(
                "SELECT id, correlation_id, status, escalated, analyst_notes FROM workbench_invoices WHERE source_path = ?",
                (source_path,),
            ).fetchone()
            if existing and existing["status"] in {"paid", "rejected"}:
                # Keep terminal outcomes; do not create a second row for the same file.
                record = self.get(int(existing["id"]))
                assert record is not None
                return record

            keep_correlation = existing["correlation_id"] if existing else correlation_id
            keep_escalated = int(existing["escalated"]) if existing else 0
            keep_notes = existing["analyst_notes"] if existing else ""
            if existing and keep_escalated and status == "pending_review":
                status = "awaiting_vp"

            vals = (
                invoice.invoice_id,
                invoice.vendor,
                str(invoice.amount),
                invoice.due_date.isoformat() if invoice.due_date else None,
                status,
                1 if invoice.is_high_value else 0,
                keep_escalated,
                1 if hard_blocked else 0,
                confidence,
                1 if self_corrected else 0,
                json.dumps(list(issues)),
                json.dumps(items),
                raw_text,
                notes,
                keep_notes,
                now,
            )
            if existing:
                conn.execute(
                    """
                    UPDATE workbench_invoices SET
                        invoice_id=?, vendor=?, amount=?, due_date=?,
                        status=?, high_value=?, escalated=?, hard_blocked=?,
                        confidence=?, self_corrected=?, issues_json=?, items_json=?,
                        raw_text=?, notes=?, analyst_notes=?, updated_at=?
                    WHERE source_path=?
                    """,
                    vals + (source_path,),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO workbench_invoices (
                        correlation_id, source_path, invoice_id, vendor, amount, due_date,
                        status, high_value, escalated, hard_blocked, confidence,
                        self_corrected, issues_json, items_json, raw_text, notes,
                        analyst_notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (keep_correlation, source_path) + vals[:-1] + (now, now),
                )
            conn.commit()
        record = self.get_by_source_path(source_path)
        assert record is not None
        return record

    def get(self, record_id: int) -> WorkbenchRecord | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workbench_invoices WHERE id = ?",
                (record_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def get_by_correlation(self, correlation_id: str) -> WorkbenchRecord | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM workbench_invoices WHERE correlation_id = ?",
                (correlation_id,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def update_fields(self, record_id: int, **fields: Any) -> WorkbenchRecord:
        allowed = {
            "invoice_id",
            "vendor",
            "amount",
            "due_date",
            "status",
            "high_value",
            "escalated",
            "hard_blocked",
            "confidence",
            "self_corrected",
            "issues_json",
            "items_json",
            "notes",
            "analyst_notes",
        }
        sets: list[str] = []
        vals: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            vals.append(value)
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(record_id)
        with connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE workbench_invoices SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
        record = self.get(record_id)
        assert record is not None
        return record

    def list_by_statuses(self, statuses: list[str]) -> list[WorkbenchRecord]:
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        with connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM workbench_invoices
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC
                """,
                statuses,
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_all(self) -> list[WorkbenchRecord]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM workbench_invoices ORDER BY updated_at DESC"
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def add_event(
        self,
        correlation_id: str,
        event_type: str,
        actor_role: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workbench_events
                    (correlation_id, event_type, actor_role, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    correlation_id,
                    event_type,
                    actor_role,
                    json.dumps(payload or {}),
                    time.time(),
                ),
            )
            conn.commit()

    def events_for(self, correlation_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM workbench_events
                WHERE correlation_id = ?
                ORDER BY id ASC
                """,
                (correlation_id,),
            ).fetchall()
        return [
            {
                "event_type": r["event_type"],
                "actor_role": r["actor_role"],
                "payload": json.loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def _initial_status(
    confidence: float,
    self_corrected: bool,
    hard_blocked: bool,
    issues: tuple[str, ...],
    invoice: Invoice,
) -> str:
    if confidence < CONFIDENCE_OVERRIDE_THRESHOLD or self_corrected:
        return "needs_override"
    if hard_blocked:
        return "pending_review"
    if any(str(i).startswith(p) for i in issues for p in ("sku_typo_review", "vendor_split_risk")):
        return "awaiting_vp"
    if issues:
        return "pending_review"
    if invoice.is_high_value:
        return "awaiting_vp"
    return "pending_review"


def _row_to_record(row: Any) -> WorkbenchRecord:
    due = None
    if row["due_date"]:
        due = date.fromisoformat(row["due_date"])
    return WorkbenchRecord(
        id=int(row["id"]),
        correlation_id=row["correlation_id"],
        source_path=row["source_path"],
        invoice_id=row["invoice_id"],
        vendor=row["vendor"],
        amount=Decimal(row["amount"]),
        due_date=due,
        status=row["status"],
        high_value=bool(row["high_value"]),
        escalated=bool(row["escalated"]),
        hard_blocked=bool(row["hard_blocked"]),
        confidence=float(row["confidence"]),
        self_corrected=bool(row["self_corrected"]),
        issues=json.loads(row["issues_json"]),
        items=json.loads(row["items_json"]),
        raw_text=row["raw_text"] or "",
        notes=row["notes"] or "",
        analyst_notes=row["analyst_notes"] or "",
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )
