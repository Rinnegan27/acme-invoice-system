"""PaymentWorker must not burn the permit before saga.pay succeeds."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from invoice_automation.agents.serialization import invoice_to_dict
from invoice_automation.agents.workers import PaymentWorker
from invoice_automation.domain.exceptions import PaymentError
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem, PaymentResult
from invoice_automation.policy.engine import PolicyError, configure_policy_engine

pytestmark = pytest.mark.white_box


def _invoice(correlation_id: str) -> Invoice:
    return Invoice(
        invoice_id="INV-RETRY",
        vendor="Widgets Inc.",
        amount=Decimal("100.00"),
        due_date=None,
        items=(LineItem("WidgetA", 1, Decimal("100.00")),),
        source_path="invoice_retry.txt",
        status=InvoiceStatus.APPROVED,
        correlation_id=correlation_id,
    )


def test_payment_worker_retries_after_transient_pay_failure(tmp_path: Path) -> None:
    db = tmp_path / "system.db"
    engine = configure_policy_engine(db_path=db, secret=b"test-secret-ok-16chars")
    inv = _invoice(correlation_id="corr-retry-1")
    permit = engine.issue_permit(inv, actor="system", open_issues=())

    calls = {"n": 0}

    class _Saga:
        def pay(self, **kwargs):  # noqa: ANN003
            calls["n"] += 1
            if calls["n"] == 1:
                raise PaymentError("transient gateway blip")
            return PaymentResult(
                status="success",
                vendor=kwargs["vendor"],
                amount=kwargs["amount"],
                idempotency_key=kwargs["idempotency_key"],
                transaction_id="tx-ok",
            )

    payload = {
        "invoice": invoice_to_dict(inv),
        "permit": permit.to_dict(),
    }
    msg = {
        "id": 1,
        "correlation_id": inv.correlation_id,
        "payload": payload,
    }

    queue = MagicMock()
    queue.dequeue.return_value = msg
    events = MagicMock()
    metrics = MagicMock()
    worker = PaymentWorker(queue, _Saga(), events, metrics)  # type: ignore[arg-type]

    # First attempt: pay fails; permit must remain reusable.
    assert worker.process_one() is True
    queue.fail.assert_called()
    engine.verify_permit(permit, inv, open_issues=(), consume=False)

    # Second attempt: pay succeeds and consumes the nonce.
    queue.fail.reset_mock()
    queue.ack.reset_mock()
    assert worker.process_one() is True
    queue.ack.assert_called()
    with pytest.raises(PolicyError, match="already consumed"):
        engine.verify_permit(permit, inv, open_issues=(), consume=True)
