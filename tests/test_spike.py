"""Spike gate: durable queue, DLQ, idempotency, payment saga/outbox."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.payment_mock import MockPaymentGateway
from invoice_automation.adapters.sqlite_queue import SqliteWorkQueue
from invoice_automation.domain.models import StageName
from invoice_automation.saga.payment_saga import PaymentSaga

SCHEMA = Path(__file__).resolve().parents[1] / "spike" / "schema.sql"


pytestmark = pytest.mark.white_box


@pytest.fixture
def queue(tmp_path: Path) -> SqliteWorkQueue:
    return SqliteWorkQueue(tmp_path / "spike.db", SCHEMA)


@pytest.fixture
def saga(tmp_path: Path) -> tuple[PaymentSaga, MockPaymentGateway]:
    gateway = MockPaymentGateway()
    return PaymentSaga(tmp_path / "saga.db", SCHEMA, gateway), gateway


def test_enqueue_dequeue_ack_idempotent(queue: SqliteWorkQueue) -> None:
    mid = queue.enqueue(
        StageName.INGESTION,
        {"invoice_id": "INV-1", "path": "a.txt"},
        idempotency_key="ing:INV-1",
        correlation_id="c1",
    )
    dup = queue.enqueue(
        StageName.INGESTION,
        {"invoice_id": "INV-1", "path": "a.txt"},
        idempotency_key="ing:INV-1",
        correlation_id="c1",
    )
    assert mid == dup

    msg = queue.dequeue(StageName.INGESTION)
    assert msg is not None
    assert msg["payload"]["invoice_id"] == "INV-1"
    queue.ack(msg["id"])

    assert queue.dequeue(StageName.INGESTION) is None
    # Re-enqueue same key after ack should be ignored (-1).
    again = queue.enqueue(
        StageName.INGESTION,
        {"invoice_id": "INV-1"},
        idempotency_key="ing:INV-1",
        correlation_id="c1",
    )
    assert again == -1


def test_dlq_after_max_failures(queue: SqliteWorkQueue) -> None:
    queue.enqueue(
        StageName.VALIDATION,
        {"invoice_id": "INV-BAD"},
        idempotency_key="val:INV-BAD",
        correlation_id="c2",
    )
    for _ in range(3):
        msg = queue.dequeue(StageName.VALIDATION, visibility_timeout_s=0.01)
        assert msg is not None
        queue.fail(msg["id"], reason="boom", max_receive_count=3)

    assert queue.dlq_count() == 1
    assert queue.dequeue(StageName.VALIDATION) is None


def test_payment_saga_no_double_pay(
    saga: tuple[PaymentSaga, MockPaymentGateway],
) -> None:
    payment_saga, gateway = saga
    r1 = payment_saga.pay(
        invoice_id="INV-1001",
        vendor="Widgets Inc.",
        amount=Decimal("5000"),
        correlation_id="c3",
    )
    r2 = payment_saga.pay(
        invoice_id="INV-1001",
        vendor="Widgets Inc.",
        amount=Decimal("5000"),
        correlation_id="c3",
    )
    assert r1.status == "success"
    assert r2.status == "success"
    assert gateway.call_count == 1
    events = payment_saga.outbox_events()
    assert any(e["event_type"] == "PaymentSucceeded" for e in events)


def test_payment_outbox_durable_after_success(
    saga: tuple[PaymentSaga, MockPaymentGateway],
) -> None:
    payment_saga, _ = saga
    payment_saga.pay(
        invoice_id="INV-1004",
        vendor="Precision Parts",
        amount=Decimal("1890"),
        correlation_id="c4",
    )
    events = payment_saga.outbox_events()
    assert len(events) == 1
    assert events[0]["aggregate_id"] == "INV-1004"
    assert events[0]["published"] == 0
