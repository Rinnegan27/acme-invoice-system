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


def _item_to_dict(item: LineItem) -> dict[str, Any]:
    return {
        "sku": item.sku,
        "quantity": item.quantity,
        "unit_price": None if item.unit_price is None else str(item.unit_price),
    }


def _item_from_dict(data: dict[str, Any]) -> LineItem:
    raw_price = data.get("unit_price")
    price = None if raw_price in (None, "") else Decimal(str(raw_price))
    return LineItem(sku=str(data["sku"]), quantity=int(data["quantity"]), unit_price=price)


class PaymentSaga:
    """Run payment_intent, outbox, and gateway.

    Parameters
    ----------
    db_path : str or Path
        SQLite path for payment_intent and outbox tables.
    schema_path : str or Path
        SQL schema applied on first open.
    gateway : PaymentGateway
        Idempotent payment adapter.
    inventory : InventoryRepository or None
        Optional stock store. When set, stock decrements after pay.

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
        source_stem: str = "",
    ) -> PaymentResult:
        """Pay one invoice through the gateway and optional stock draw.

        Parameters
        ----------
        invoice_id : str
            Business payment aggregate id (normalized ``INV-…``).
        vendor : str
            Payee name.
        amount : Decimal
            Amount to pay.
        correlation_id : str
            Trace id for outbox and alerts.
        idempotency_key : str or None
            Gateway key. Defaults to ``pay:{invoice_id}``.
        items : sequence of LineItem
            Lines for stock decrement. Empty skips stock.
        source_stem : str
            Source file stem for audit only (not the aggregate key).

        Returns
        -------
        PaymentResult
            Gateway result. Replay of RECONCILE returns ``status="reconcile"``.

        Raises
        ------
        PaymentError
            Gateway failure, or stock failure after a successful gateway pay
            (message prefix ``stock_reconcile_required:``).
        """
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
        except PaymentError as exc:
            self._finalize_failure(invoice_id, correlation_id, str(exc), source_stem=source_stem)
            raise
        except Exception as exc:
            # Gateway boundary: wrap unknown adapter errors as PaymentError.
            self._finalize_failure(invoice_id, correlation_id, str(exc), source_stem=source_stem)
            raise PaymentError(str(exc)) from exc

        if result.status != "success":
            self._finalize_failure(
                invoice_id, correlation_id, result.status, source_stem=source_stem
            )
            raise PaymentError(f"payment failed: {result.status}")

        if self._inventory is not None and items:
            try:
                self._inventory.decrement_stock(items)
            except ValidationError as exc:
                # Gateway paid. Stock failed. Hold for ops; do not mark FAILED.
                self._finalize_reconcile(
                    invoice_id,
                    correlation_id,
                    result,
                    str(exc),
                    source_stem=source_stem,
                    items=items,
                )
                raise PaymentError(f"stock_reconcile_required:{exc}") from exc

        self._finalize_success(invoice_id, correlation_id, result, source_stem=source_stem)
        return result

    def _finalize_success(
        self,
        invoice_id: str,
        correlation_id: str,
        result: PaymentResult,
        *,
        source_stem: str = "",
    ) -> None:
        now = time.time()
        payload = {
            "invoice_id": invoice_id,
            "vendor": result.vendor,
            "amount": str(result.amount),
            "idempotency_key": result.idempotency_key,
            "transaction_id": result.transaction_id,
            "source_stem": source_stem,
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
        *,
        source_stem: str = "",
        items: Sequence[LineItem] = (),
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
            "source_stem": source_stem,
            "items": [_item_to_dict(i) for i in items],
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

    def list_reconcile_intents(self) -> list[dict[str, Any]]:
        """Return open pay/stock reconcile rows with latest outbox payload."""
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM payment_intent
                WHERE status = 'RECONCILE' AND needs_manual_reconciliation = 1
                ORDER BY updated_at DESC
                """
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                payload = self._latest_reconcile_payload(conn, str(item["invoice_id"]))
                item["reason"] = str(payload.get("reason") or "")
                item["items"] = list(payload.get("items") or [])
                item["transaction_id"] = str(payload.get("transaction_id") or "")
                out.append(item)
            return out

    def retry_stock_decrement(self, invoice_id: str) -> PaymentResult:
        """Retry inventory draw for a RECONCILE intent after stock is fixed.

        Parameters
        ----------
        invoice_id : str
            Business payment aggregate id.

        Returns
        -------
        PaymentResult
            Success result when stock decrements and the intent is closed.

        Raises
        ------
        PaymentError
            When the intent is missing, not in RECONCILE, items are missing,
            inventory is unset, or stock still fails.
        """
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM payment_intent WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
            if row is None:
                raise PaymentError(f"no payment intent for {invoice_id}")
            if row["status"] != "RECONCILE":
                raise PaymentError(f"payment intent {invoice_id} is {row['status']}, not RECONCILE")
            payload = self._latest_reconcile_payload(conn, invoice_id)
            correlation_id = str(row["correlation_id"])
            source_stem = str(payload.get("source_stem") or "")
            items = [_item_from_dict(i) for i in (payload.get("items") or [])]
            result = PaymentResult(
                status="success",
                vendor=str(row["vendor"]),
                amount=Decimal(str(row["amount"])),
                idempotency_key=str(row["idempotency_key"]),
                transaction_id=str(payload.get("transaction_id") or f"reconcile:{invoice_id}"),
            )

        if self._inventory is None:
            raise PaymentError("inventory adapter is not configured")
        if not items:
            raise PaymentError(f"no line items stored for reconcile retry on {invoice_id}")
        try:
            self._inventory.decrement_stock(items)
        except ValidationError as exc:
            raise PaymentError(f"stock_reconcile_required:{exc}") from exc

        self._finalize_success(invoice_id, correlation_id, result, source_stem=source_stem)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE payment_intent
                SET needs_manual_reconciliation = 0, updated_at = ?
                WHERE invoice_id = ?
                """,
                (time.time(), invoice_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (aggregate_id, event_type, payload, correlation_id)
                VALUES (?, 'PaymentReconcileResolved', ?, ?)
                """,
                (
                    invoice_id,
                    json.dumps(
                        {
                            "invoice_id": invoice_id,
                            "action": "retry_stock",
                            "transaction_id": result.transaction_id,
                        }
                    ),
                    correlation_id,
                ),
            )
            conn.commit()
        return result

    def acknowledge_reconcile(self, invoice_id: str, *, note: str = "") -> None:
        """Close a RECONCILE intent without retrying stock (ops ack).

        Parameters
        ----------
        invoice_id : str
            Business payment aggregate id.
        note : str
            Operator note stored on the outbox event.

        Raises
        ------
        PaymentError
            When the intent is missing or not in RECONCILE.
        """
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM payment_intent WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
            if row is None:
                raise PaymentError(f"no payment intent for {invoice_id}")
            if row["status"] != "RECONCILE":
                raise PaymentError(f"payment intent {invoice_id} is {row['status']}, not RECONCILE")
            correlation_id = str(row["correlation_id"])
            now = time.time()
            conn.execute(
                """
                UPDATE payment_intent
                SET status = 'SUCCEEDED',
                    needs_manual_reconciliation = 0,
                    updated_at = ?
                WHERE invoice_id = ?
                """,
                (now, invoice_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (aggregate_id, event_type, payload, correlation_id)
                VALUES (?, 'PaymentReconcileAcked', ?, ?)
                """,
                (
                    invoice_id,
                    json.dumps(
                        {
                            "invoice_id": invoice_id,
                            "action": "ack",
                            "note": note,
                            "stock_status": "skipped",
                        }
                    ),
                    correlation_id,
                ),
            )
            conn.commit()

    @staticmethod
    def _latest_reconcile_payload(conn: Any, invoice_id: str) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT payload FROM outbox
            WHERE aggregate_id = ? AND event_type = 'PaymentStockReconcile'
            ORDER BY id DESC LIMIT 1
            """,
            (invoice_id,),
        ).fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _finalize_failure(
        self,
        invoice_id: str,
        correlation_id: str,
        reason: str,
        *,
        source_stem: str = "",
    ) -> None:
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
                (
                    invoice_id,
                    json.dumps({"reason": reason, "source_stem": source_stem}),
                    correlation_id,
                ),
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
        # All outbox rows in id order (published and unpublished).
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM outbox ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def mark_outbox_published(self, outbox_id: int) -> None:
        # Mark one outbox row published after JSONL emit.
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE outbox SET published = 1 WHERE id = ?",
                (outbox_id,),
            )
            conn.commit()
