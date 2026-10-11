"""Payment saga with transactional outbox for crash-safe audit."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoice_automation.adapters.sqlite_db import apply_schema, connect
from invoice_automation.domain.exceptions import PaymentError, ValidationError
from invoice_automation.domain.models import LineItem, PaymentResult
from invoice_automation.ports.contracts import InventoryRepository, PaymentGateway


class PaymentSaga:
    """Run payment_intent, outbox, and gateway.

    Notes
    -----
    The gateway call is outside the DB transaction.
    1. Create or update PaymentIntent as PENDING.
    2. Call the gateway with the idempotency key.
    3. Decrement inventory stock.
    4. If stock fails after a successful pay, set RECONCILE and emit
       ``PaymentStockReconcile``. Do not mark the pay as failed.
    5. On full success, set SUCCEEDED and write ``PaymentSucceeded``.
    """

    def __init__(
        self,
        db_path: str | Path,
        schema_path: str | Path,
        gateway: PaymentGateway,
        inventory: InventoryRepository | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._gateway = gateway
        self._inventory = inventory
        with connect(self.db_path) as conn:
            apply_schema(conn, schema_path)

    def pay(
        self,
        *,
        invoice_id: str,
        vendor: str,
        amount: Decimal,
        correlation_id: str,
        idempotency_key: str | None = None,
        items: Sequence[LineItem] = (),
    ) -> PaymentResult:
        key = idempotency_key or f"pay:{invoice_id}"
        with connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM payment_intent WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
            if existing and existing["status"] in {"SUCCEEDED", "RECONCILE"}:
                return PaymentResult(
                    status="success" if existing["status"] == "SUCCEEDED" else "reconcile",
                    vendor=existing["vendor"],
                    amount=Decimal(existing["amount"]),
                    idempotency_key=existing["idempotency_key"],
                    transaction_id=f"replay:{existing['id']}",
                )
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO payment_intent (
                        invoice_id, vendor, amount, status, idempotency_key, correlation_id
                    ) VALUES (?, ?, ?, 'PENDING', ?, ?)
                    """,
                    (invoice_id, vendor, str(amount), key, correlation_id),
                )
                conn.commit()
            else:
                key = existing["idempotency_key"]

        try:
            result = self._gateway.pay(key, vendor, amount)
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised as domain error
            self._finalize_failure(invoice_id, correlation_id, str(exc))
            raise PaymentError(str(exc)) from exc

        if result.status != "success":
            self._finalize_failure(invoice_id, correlation_id, result.status)
            raise PaymentError(f"payment failed: {result.status}")

        if self._inventory is not None and items:
            try:
                self._inventory.decrement_stock(items)
            except ValidationError as exc:
                # Gateway paid. Stock failed. Hold for ops; do not mark FAILED.
                self._finalize_reconcile(invoice_id, correlation_id, result, str(exc))
                raise PaymentError(f"stock_reconcile_required:{exc}") from exc

        self._finalize_success(invoice_id, correlation_id, result)
        return result

    def _finalize_success(
        self,
        invoice_id: str,
        correlation_id: str,
        result: PaymentResult,
    ) -> None:
        now = time.time()
        payload = {
            "invoice_id": invoice_id,
            "vendor": result.vendor,
            "amount": str(result.amount),
            "idempotency_key": result.idempotency_key,
            "transaction_id": result.transaction_id,
        }
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE payment_intent
                SET status = 'SUCCEEDED', updated_at = ?
                WHERE invoice_id = ?
                """,
                (now, invoice_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (aggregate_id, event_type, payload, correlation_id)
                VALUES (?, 'PaymentSucceeded', ?, ?)
                """,
                (invoice_id, json.dumps(payload), correlation_id),
            )
            conn.commit()

    def _finalize_reconcile(
        self,
        invoice_id: str,
        correlation_id: str,
        result: PaymentResult,
        reason: str,
    ) -> None:
        # Gateway paid. Stock failed. Hold for ops.
        now = time.time()
        payload = {
            "invoice_id": invoice_id,
            "vendor": result.vendor,
            "amount": str(result.amount),
            "idempotency_key": result.idempotency_key,
            "transaction_id": result.transaction_id,
            "reason": reason,
            "gateway_status": "success",
            "stock_status": "failed",
        }
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE payment_intent
                SET status = 'RECONCILE',
                    needs_manual_reconciliation = 1,
                    updated_at = ?
                WHERE invoice_id = ?
                """,
                (now, invoice_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (aggregate_id, event_type, payload, correlation_id)
                VALUES (?, 'PaymentStockReconcile', ?, ?)
                """,
                (invoice_id, json.dumps(payload), correlation_id),
            )
            conn.execute(
                """
                INSERT INTO alerts (severity, message, correlation_id)
                VALUES ('error', ?, ?)
                """,
                (
                    f"stock reconcile required for {invoice_id}: gateway paid; {reason}",
                    correlation_id,
                ),
            )
            conn.commit()

    def _finalize_failure(self, invoice_id: str, correlation_id: str, reason: str) -> None:
        now = time.time()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE payment_intent
                SET status = 'FAILED',
                    needs_manual_reconciliation = 1,
                    updated_at = ?
                WHERE invoice_id = ?
                """,
                (now, invoice_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (aggregate_id, event_type, payload, correlation_id)
                VALUES (?, 'PaymentFailed', ?, ?)
                """,
                (invoice_id, json.dumps({"reason": reason}), correlation_id),
            )
            conn.execute(
                """
                INSERT INTO alerts (severity, message, correlation_id)
                VALUES ('error', ?, ?)
                """,
                (f"payment failure for {invoice_id}: {reason}", correlation_id),
            )
            conn.commit()

    def outbox_events(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM outbox ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def mark_outbox_published(self, outbox_id: int) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE outbox SET published = 1 WHERE id = ?",
                (outbox_id,),
            )
            conn.commit()
