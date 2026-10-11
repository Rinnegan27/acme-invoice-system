"""Abstract contracts (Protocols) for external dependencies."""

from invoice_automation.ports.contracts import (
    EventSink,
    InventoryRepository,
    LLMClient,
    MetricsCollector,
    PaymentGateway,
    WorkQueue,
)

__all__ = [
    "EventSink",
    "InventoryRepository",
    "LLMClient",
    "MetricsCollector",
    "PaymentGateway",
    "WorkQueue",
]
