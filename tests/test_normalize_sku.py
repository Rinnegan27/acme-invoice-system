"""SKU annotation stripping (live Grok false-positive guardrail)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.domain.models import (
    Invoice,
    InvoiceStatus,
    LineItem,
    normalize_sku,
)
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.invariants import collect_invariant_issues

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("WidgetA", "WidgetA"),
        ("WidgetA (rush order)", "WidgetA"),
        ("WidgetA(rush order)", "WidgetA"),
        ("GadgetX (expedited)", "GadgetX"),
        ("  WidgetB (priority)  ", "WidgetB"),
        ("FakeItem", "FakeItem"),
    ],
)
def test_normalize_sku_strips_trailing_parens(raw: str, expected: str) -> None:
    assert normalize_sku(raw) == expected


def test_line_item_normalizes_sku_on_construct() -> None:
    item = LineItem(sku="WidgetA (rush order)", quantity=4, unit_price=Decimal("300"))
    assert item.sku == "WidgetA"


def test_rush_annotation_not_charset_issue() -> None:
    from datetime import date

    items = (
        LineItem("WidgetA", 8, Decimal("250")),
        LineItem("WidgetB", 4, Decimal("500")),
        LineItem("GadgetX", 2, Decimal("750")),
        LineItem("WidgetA (rush order)", 4, Decimal("300")),
    )
    assert [i.sku for i in items] == ["WidgetA", "WidgetB", "GadgetX", "WidgetA"]
    inv = Invoice(
        invoice_id="INV-1010",
        vendor="Consolidated Materials Group",
        amount=Decimal("7185"),
        due_date=date(2026, 2, 26),
        items=items,
        source_path="data/invoices/invoice_1010.txt",
        status=InvoiceStatus.EXTRACTED,
    )
    issues = collect_invariant_issues(inv)
    assert not any(i.startswith("invalid_sku_charset") for i in issues)


def test_stub_pipeline_pays_invoice_1010(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "r", use_grok=False, profile="case")
    result = pipe.process_file(DATA / "invoice_1010.txt")
    assert result.status == "paid"
    assert result.issues == ()
