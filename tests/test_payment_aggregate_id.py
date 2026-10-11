"""Payment saga keys by business INV- id; source stem is metadata only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from invoice_automation.agents.serialization import invoice_to_dict
from invoice_automation.agents.workers import PaymentWorker
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem, PaymentResult
from invoice_automation.policy.engine import configure_policy_engine

pytestmark = pytest.mark.white_box


def test_payment_worker_keys_saga_by_inv_id(tmp_path: Path) -> None:
    db = tmp_path / "system.db"
    engine = configure_policy_engine(db_path=db, secret=b"test-secret-ok-16chars")
    inv = Invoice(
        invoice_id="INV-1001",
        vendor="Widgets Inc.",
        amount=Decimal("100.00"),
        due_date=None,
        items=(LineItem("WidgetA", 1, Decimal("100.00")),),
        source_path="invoice_1001.txt",
        status=InvoiceStatus.APPROVED,
        correlation_id="corr-agg-1",
    )
    permit = engine.issue_permit(inv, actor="system", open_issues=())

    captured: dict[str, object] = {}

    class _Saga:
        def pay(self, **kwargs):  # noqa: ANN003
            captured.update(kwargs)
            return PaymentResult(
                status="success",
                vendor=kwargs["vendor"],
                amount=kwargs["amount"],
                idempotency_key=kwargs["idempotency_key"],
                transaction_id="tx-1",
            )

    msg = {
        "id": 1,
        "correlation_id": inv.correlation_id,
        "payload": {"invoice": invoice_to_dict(inv), "permit": permit.to_dict()},
    }
    queue = MagicMock()
    queue.dequeue.return_value = msg
    worker = PaymentWorker(queue, _Saga(), MagicMock(), MagicMock())  # type: ignore[arg-type]
    assert worker.process_one() is True
    assert captured["invoice_id"] == "INV-1001"
    assert captured["source_stem"] == "invoice_1001"
    assert captured["idempotency_key"] == "pay:INV-1001"
