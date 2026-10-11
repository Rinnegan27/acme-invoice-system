"""Parser unit tests against Galatiq sample formats."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.parsers import parse_invoice_text

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


@pytest.mark.parametrize(
    ("name", "invoice_id", "sku"),
    [
        ("invoice_1001.txt", "INV-1001", "WidgetA"),
        ("invoice_1004.json", "INV-1004", "WidgetA"),
        ("invoice_1006.csv", "INV-1006", "WidgetA"),
        ("invoice_1007.csv", "INV-1007", "WidgetA"),
        ("invoice_1014.xml", "INV-1014", "WidgetA"),
        ("invoice_1015.csv", "INV-1015", "GadgetX"),
    ],
)
def test_core_formats(name: str, invoice_id: str, sku: str) -> None:
    path = DATA / name
    inv = parse_invoice_text(path.read_text(encoding="utf-8"), str(path))
    assert inv.invoice_id == invoice_id
    assert any(i.sku == sku for i in inv.items)
    assert inv.amount > 0


def test_messy_1002() -> None:
    path = DATA / "invoice_1002.txt"
    inv = parse_invoice_text(path.read_text(encoding="utf-8"), str(path))
    assert inv.invoice_id == "INV-1002"
    assert inv.items[0].sku == "GadgetX"
    assert inv.items[0].quantity == 20
    assert inv.amount == Decimal("15000.00")


def test_nested_vendor_json() -> None:
    path = DATA / "invoice_1004.json"
    inv = parse_invoice_text(path.read_text(encoding="utf-8"), str(path))
    assert inv.vendor == "Precision Parts Ltd."
