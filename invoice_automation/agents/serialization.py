"""Serialize/deserialize Invoice DTOs for queue payloads."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem


def invoice_to_dict(invoice: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.invoice_id,
        "vendor": invoice.vendor,
        "amount": str(invoice.amount),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "items": [
            {
                "sku": i.sku,
                "quantity": i.quantity,
                "unit_price": str(i.unit_price) if i.unit_price is not None else None,
            }
            for i in invoice.items
        ],
        "source_path": invoice.source_path,
        "status": invoice.status.value,
        "issues": list(invoice.issues),
        "correlation_id": invoice.correlation_id,
        "approval_reason": invoice.approval_reason,
    }


def invoice_from_dict(data: dict[str, Any]) -> Invoice:
    due: date | None = None
    if data.get("due_date"):
        due = date.fromisoformat(str(data["due_date"]))
    items = tuple(
        LineItem(
            sku=str(i["sku"]),
            quantity=int(i["quantity"]),
            unit_price=Decimal(str(i["unit_price"])) if i.get("unit_price") is not None else None,
        )
        for i in data.get("items", [])
    )
    return Invoice(
        invoice_id=str(data["invoice_id"]),
        vendor=str(data["vendor"]),
        amount=Decimal(str(data["amount"])),
        due_date=due,
        items=items,
        source_path=str(data.get("source_path", "")),
        status=InvoiceStatus(str(data.get("status", "received"))),
        issues=tuple(data.get("issues") or ()),
        correlation_id=str(data.get("correlation_id") or ""),
        approval_reason=str(data.get("approval_reason") or ""),
    )
