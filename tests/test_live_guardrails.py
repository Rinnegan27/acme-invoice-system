"""Deterministic guardrails that keep live Grok from soft-spot bypasses."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.parsers import assert_raw_quantity_integrity
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.invariants import VENDOR_INJECTION_REVIEW_PREFIX
from invoice_automation.policy.sku_resolve import (
    soft_issues_from_source_items,
    undo_digit_sku_expansions,
)

pytestmark = pytest.mark.white_box


def test_assert_raw_qty_rejects_approx_and_float() -> None:
    with pytest.raises(ExtractionError, match="invalid_quantity"):
        assert_raw_quantity_integrity("Item: WidgetA\nQty: ~5\n")
    with pytest.raises(ExtractionError, match="invalid_quantity"):
        assert_raw_quantity_integrity("Item: GadgetX\nQty: 5.0000001\n")


def test_undo_digit_sku_expansions_restores_widg3ta() -> None:
    raw = "Item: Widg3tA\nQty: 3\n"
    items = (LineItem("WidgetA", 3, Decimal("250")),)
    out = undo_digit_sku_expansions(raw, items)
    assert out[0].sku == "Widg3tA"


def test_soft_issues_widget_alpha_escalates() -> None:
    raw = "Item: Widget Alpha\nQty: 1\n"
    items = (LineItem("WidgetA", 1, Decimal("250")),)
    soft = soft_issues_from_source_items(raw, items)
    assert any("Widget Alpha" in s and "WidgetA" in s for s in soft)


def test_soft_issues_widget_a_exact_stays_silent() -> None:
    raw = "Item: Widget A\nQty: 5\n"
    items = (LineItem("WidgetA", 5, Decimal("250")),)
    soft = soft_issues_from_source_items(raw, items)
    assert soft == []


def test_pipeline_widg3ta_rejects(tmp_path: Path) -> None:
    path = tmp_path / "n02.txt"
    path.write_text(
        "Invoice Number: INV-9102\nVendor: SupplyCo\nItem: Widg3tA\n"
        "Qty: 3\nUnit Price: $250\nTotal: $750\n",
        encoding="utf-8",
    )
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status == "rejected"
    assert any("unknown_item" in i for i in result.issues)


def test_pipeline_approx_qty_fails(tmp_path: Path) -> None:
    path = tmp_path / "n05.txt"
    path.write_text(
        "Invoice Number: INV-9205\nVendor: Approx Co\nItem: WidgetA\n"
        "Qty: ~5\nUnit Price: $250\nTotal: $1250\n",
        encoding="utf-8",
    )
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status in {"failed", "rejected"}


def test_pipeline_sql_vendor_pays_after_vp(tmp_path: Path) -> None:
    path = tmp_path / "inj.txt"
    path.write_text(
        "Invoice Number: INV-9406\nVendor: '; DROP TABLE inventory; --\n"
        "Item: WidgetA\nQty: 1\nUnit Price: $250\nTotal: $250\n",
        encoding="utf-8",
    )
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status == "paid"
    assert any(i.startswith(VENDOR_INJECTION_REVIEW_PREFIX) for i in result.issues) or any(
        VENDOR_INJECTION_REVIEW_PREFIX in str(e) for e in pipe.events.read_all() for e in [e]
    )
    # Soft must have been present at validation/approval (paid via VP override).
    events = pipe.events.read_all()
    validated = next(e for e in events if e["event_type"] == "InvoiceValidated")
    soft = validated["payload"].get("soft_escalations") or []
    assert any(str(s).startswith(VENDOR_INJECTION_REVIEW_PREFIX) for s in soft)
