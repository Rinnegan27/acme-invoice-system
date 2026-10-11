"""Protocol contracts for inventory, LLM, payment, queue, and telemetry.

Notes
-----
Adapters implement these Protocols. Domain code depends on the Protocols,
not on concrete SQLite or HTTP clients.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from invoice_automation.domain.models import (
    ApprovalDecision,
    ExtractionResult,
    Invoice,
    LineItem,
    PaymentResult,
    StageName,
)


@runtime_checkable
class InventoryRepository(Protocol):
    """Inventory availability checks."""

    def check_availability(self, items: Sequence[LineItem]) -> list[str]:
        """Return issue codes; empty list means valid."""
        ...

    def decrement_stock(self, items: Sequence[LineItem]) -> None:
        """Decrement stock after a successful payment. Raise on shortfall."""
        ...

    def reseed(self) -> None:
        """Restore seed stock and master data (demo / sim hygiene)."""
        ...


@runtime_checkable
class LLMClient(Protocol):
    """LLM reasoning boundary for extract and approval."""

    def extract(
        self, raw_text: str, source_path: str, deadline_s: float = 30.0
    ) -> ExtractionResult:
        """Extract structured invoice data from raw document text."""
        ...

    def approve(self, invoice: Invoice, deadline_s: float = 30.0) -> ApprovalDecision:
        """Produce a VP-level approval decision with optional reflection."""
        ...


@runtime_checkable
class PaymentGateway(Protocol):
    """Idempotent payment gateway."""

    def pay(
        self,
        idempotency_key: str,
        vendor: str,
        amount: Decimal,
    ) -> PaymentResult:
        """Execute or replay a payment for the given idempotency key."""
        ...


@runtime_checkable
class WorkQueue(Protocol):
    """Durable stage queue."""

    def enqueue(
        self,
        stage: StageName,
        payload: dict[str, Any],
        idempotency_key: str,
        correlation_id: str,
    ) -> int:
        """Enqueue work; returns message id (existing id if duplicate)."""
        ...

    def dequeue(
        self,
        stage: StageName,
        visibility_timeout_s: float = 30.0,
    ) -> dict[str, Any] | None:
        """Claim one visible message or return None."""
        ...

    def ack(self, message_id: int) -> None:
        """Acknowledge successful processing and remove from queue."""
        ...

    def fail(self, message_id: int, reason: str, max_receive_count: int = 3) -> None:
        """Nack; move to DLQ when receive_count exceeds max."""
        ...


@runtime_checkable
class EventSink(Protocol):
    """Append-only structured event log."""

    def emit(
        self,
        event_type: str,
        correlation_id: str,
        invoice_id: str,
        payload: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> None:
        """Persist one structured event."""
        ...


@runtime_checkable
class MetricsCollector(Protocol):
    """RED-style metrics hooks."""

    def observe_latency(self, stage: str, seconds: float) -> None:
        """Record stage latency."""
        ...

    def incr_error(self, stage: str, error_class: str) -> None:
        """Increment error counter."""
        ...

    def incr_rate(self, stage: str, outcome: str) -> None:
        """Increment traffic/outcome counter."""
        ...

    def snapshot(self) -> dict[str, Any]:
        """Return current metrics snapshot."""
        ...
