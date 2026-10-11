"""Immutable domain DTOs for the invoice pipeline.

Notes
-----
Use frozen dataclasses so stage hand-offs cannot mutate shared state.
Quantity and amount guards fail fast at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Final
from uuid import uuid4

HIGH_VALUE_THRESHOLD: Final[Decimal] = Decimal("10000")


class InvoiceStatus(str, Enum):
    """Lifecycle status of an invoice."""

    RECEIVED = "received"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class StageName(str, Enum):
    """Durable queue stage names."""

    INGESTION = "ingestion"
    VALIDATION = "validation"
    APPROVAL = "approval"
    PAYMENT = "payment"


@dataclass(frozen=True)
class LineItem:
    """Immutable invoice line item.

    Parameters
    ----------
    sku : str
        Inventory SKU / product name.
    quantity : int
        Ordered quantity; must be positive for payment paths.
    unit_price : Decimal or None
        Optional unit price.

    Raises
    ------
    ValueError
        If ``sku`` is empty.
    """

    sku: str
    quantity: int
    unit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.sku or not self.sku.strip():
            raise ValueError("sku must be non-empty")


@dataclass(frozen=True)
class Invoice:
    """Core immutable invoice DTO.

    Parameters
    ----------
    invoice_id : str
        Business invoice identifier.
    vendor : str
        Vendor / supplier name.
    amount : Decimal
        Total amount due.
    due_date : date or None
        Optional due date.
    items : tuple of LineItem
        Line items.
    source_path : str
        Source file path or upload name.
    status : InvoiceStatus
        Current lifecycle status.
    issues : tuple of str
        Validation or policy issue codes.
    correlation_id : str
        Trace correlation id.
    approval_reason : str
        Human-readable approval/rejection reason.
    """

    invoice_id: str
    vendor: str
    amount: Decimal
    due_date: date | None
    items: tuple[LineItem, ...]
    source_path: str
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    issues: tuple[str, ...] = ()
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    approval_reason: str = ""

    def with_updates(
        self,
        *,
        status: InvoiceStatus | None = None,
        issues: tuple[str, ...] | None = None,
        approval_reason: str | None = None,
        invoice_id: str | None = None,
        vendor: str | None = None,
        amount: Decimal | None = None,
        due_date: date | None = None,
        items: tuple[LineItem, ...] | None = None,
        source_path: str | None = None,
        correlation_id: str | None = None,
    ) -> Invoice:
        """Return a new invoice with selected fields replaced.

        Returns
        -------
        Invoice
            Updated immutable invoice.
        """
        return Invoice(
            invoice_id=invoice_id if invoice_id is not None else self.invoice_id,
            vendor=vendor if vendor is not None else self.vendor,
            amount=amount if amount is not None else self.amount,
            due_date=due_date if due_date is not None else self.due_date,
            items=items if items is not None else self.items,
            source_path=source_path if source_path is not None else self.source_path,
            status=status if status is not None else self.status,
            issues=issues if issues is not None else self.issues,
            correlation_id=(correlation_id if correlation_id is not None else self.correlation_id),
            approval_reason=(
                approval_reason if approval_reason is not None else self.approval_reason
            ),
        )

    @property
    def is_high_value(self) -> bool:
        """Return True when amount exceeds the VP scrutiny threshold."""
        return self.amount > HIGH_VALUE_THRESHOLD


@dataclass(frozen=True)
class ExtractionResult:
    """Result of ingestion / LLM extraction."""

    invoice: Invoice
    raw_confidence: float = 1.0
    self_corrected: bool = False
    notes: str = ""


@dataclass(frozen=True)
class ApprovalDecision:
    """VP / policy approval decision."""

    approved: bool
    reason: str
    reflected: bool = False


@dataclass(frozen=True)
class PaymentResult:
    """Mock payment gateway result."""

    status: str
    vendor: str
    amount: Decimal
    idempotency_key: str
    transaction_id: str = ""
