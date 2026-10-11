from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional
import uuid


class InvoiceStatus(str, Enum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


@dataclass(frozen=True)
class LineItem:
    sku: str
    quantity: int
    unit_price: Optional[Decimal] = None


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    vendor: str
    amount: Decimal
    due_date: Optional[date]
    items: tuple[LineItem, ...]
    source_path: str
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    issues: tuple[str, ...] = field(default_factory=tuple)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def with_status(self, status: InvoiceStatus, issues: tuple[str, ...] = ()) -> "Invoice":
        return Invoice(
            invoice_id=self.invoice_id,
            vendor=self.vendor,
            amount=self.amount,
            due_date=self.due_date,
            items=self.items,
            source_path=self.source_path,
            status=status,
            issues=issues or self.issues,
            correlation_id=self.correlation_id,
        )
