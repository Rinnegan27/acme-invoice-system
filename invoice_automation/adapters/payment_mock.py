"""Idempotent mock payment gateway around the case-brief mock_payment API."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from invoice_automation.case_brief import mock_payment
from invoice_automation.domain.models import PaymentResult


class MockPaymentGateway:
    """In-memory payment gateway for the local prototype.

    On the first pay for a key, this class calls
    ``mock_payment(vendor, amount)`` from the case brief.
    """

    def __init__(self) -> None:
        self._seen: dict[str, PaymentResult] = {}
        self.call_count = 0

    def pay(
        self,
        idempotency_key: str,
        vendor: str,
        amount: Decimal,
    ) -> PaymentResult:
        if idempotency_key in self._seen:
            return self._seen[idempotency_key]
        self.call_count += 1
        # Case brief API (prints "Paid {amount} to {vendor}"):
        brief = mock_payment(vendor, amount)
        result = PaymentResult(
            status=brief.get("status", "success"),
            vendor=vendor,
            amount=amount,
            idempotency_key=idempotency_key,
            transaction_id=str(uuid4()),
        )
        self._seen[idempotency_key] = result
        return result
