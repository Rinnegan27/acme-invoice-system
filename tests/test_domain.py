"""Domain model tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem

pytestmark = pytest.mark.white_box


def test_line_item_requires_sku() -> None:
    with pytest.raises(ValueError):
        LineItem(sku="  ", quantity=1)


def test_invoice_with_updates_preserves_correlation() -> None:
    inv = Invoice(
        invoice_id="INV-1",
        vendor="Acme",
        amount=Decimal("10"),
        due_date=None,
        items=(LineItem(sku="WidgetA", quantity=1),),
        source_path="x.txt",
    )
    updated = inv.with_updates(status=InvoiceStatus.PAID)
    assert updated.correlation_id == inv.correlation_id
    assert updated.status == InvoiceStatus.PAID
    assert inv.status == InvoiceStatus.RECEIVED


def test_high_value_threshold() -> None:
    inv = Invoice(
        invoice_id="INV-1",
        vendor="Acme",
        amount=Decimal("10000.01"),
        due_date=None,
        items=(LineItem(sku="WidgetA", quantity=1),),
        source_path="x.txt",
    )
    assert inv.is_high_value
