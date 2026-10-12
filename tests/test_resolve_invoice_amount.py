"""Amount resolution: TOTAL → SUBTOTAL → priced line sum."""

from __future__ import annotations

from decimal import Decimal

import pytest

from invoice_automation.adapters.parsers import (
    line_items_amount,
    parse_invoice_text,
    resolve_invoice_amount,
)
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import LineItem

pytestmark = pytest.mark.white_box


def test_resolve_prefers_explicit_total() -> None:
    items = [LineItem(sku="WidgetA", quantity=2, unit_price=Decimal("250"))]
    assert resolve_invoice_amount(
        explicit=Decimal("999"),
        items=items,
        subtotal=Decimal("500"),
    ) == Decimal("999")


def test_resolve_uses_subtotal_when_total_missing() -> None:
    items = [LineItem(sku="WidgetA", quantity=2, unit_price=Decimal("250"))]
    assert resolve_invoice_amount(
        explicit=None,
        items=items,
        subtotal=Decimal("500"),
    ) == Decimal("500")


def test_resolve_sums_priced_lines() -> None:
    items = [
        LineItem(sku="WidgetA", quantity=2, unit_price=Decimal("250")),
        LineItem(sku="WidgetB", quantity=1, unit_price=Decimal("100")),
    ]
    assert line_items_amount(items) == Decimal("600")
    assert resolve_invoice_amount(explicit=None, items=items) == Decimal("600")


def test_resolve_fails_when_any_line_unpriced() -> None:
    items = [
        LineItem(sku="WidgetA", quantity=2, unit_price=Decimal("250")),
        LineItem(sku="WidgetB", quantity=1, unit_price=None),
    ]
    with pytest.raises(ExtractionError, match="invalid_amount"):
        resolve_invoice_amount(explicit=None, items=items)


def test_json_null_amount_computes_from_lines() -> None:
    raw = """{
  "invoice_id": "INV-COMPUTE",
  "vendor": "Widgets Inc.",
  "amount": null,
  "items": [
    {"sku": "WidgetA", "quantity": 2, "unit_price": 250.00}
  ]
}
"""
    inv = parse_invoice_text(raw, "compute.json")
    assert inv.amount == Decimal("500.00")


def test_text_subtotal_without_total() -> None:
    raw = """INVOICE
Vendor: Widgets Inc.
Invoice Number: INV-SUBONLY
Items:
  WidgetA    qty: 2    unit price: $250.00
Subtotal: $500.00
"""
    inv = parse_invoice_text(raw, "subonly.txt")
    assert inv.amount == Decimal("500.00")
