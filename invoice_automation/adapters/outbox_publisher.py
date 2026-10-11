"""Flush PaymentSaga outbox rows into the JSONL event log."""

from __future__ import annotations

import json
from typing import Any

from invoice_automation.ports.contracts import EventSink
from invoice_automation.saga.payment_saga import PaymentSaga


class OutboxPublisher:
    """Publish unpublished saga outbox events to the structured event sink."""

    def __init__(self, saga: PaymentSaga, events: EventSink) -> None:
        self.saga = saga
        self.events = events

    def flush(self) -> int:
        """Publish all unpublished outbox rows. Returns count published."""
        published = 0
        for row in self.saga.outbox_events():
            if int(row.get("published") or 0) == 1:
                continue
            payload: dict[str, Any]
            raw = row.get("payload") or "{}"
            try:
                payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            # Keep event type PaymentOutboxPublished. Put saga type in payload.
            payload = {
                **payload,
                "source": "outbox",
                "outbox_id": row["id"],
                "saga_event_type": str(row.get("event_type") or ""),
            }
            self.events.emit(
                "PaymentOutboxPublished",
                str(row.get("correlation_id") or ""),
                str(row.get("aggregate_id") or ""),
                payload,
                stage="payment",
            )
            self.saga.mark_outbox_published(int(row["id"]))
            published += 1
        return published
