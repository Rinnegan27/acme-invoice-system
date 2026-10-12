"""SKU spaced-label typo detection escalates to VP instead of silent auto-pay."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.invariants import (
    detect_sku_typo_reviews,
    partition_sku_typo_issues,
)

pytestmark = pytest.mark.white_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"


def test_detect_spaced_catalog_typos() -> None:
    raw = "Widget A  12\nGadget X  4\nWidgetB 7"
    items = (
        LineItem("WidgetA", 12, Decimal("250")),
        LineItem("WidgetB", 7, Decimal("500")),
        LineItem("GadgetX", 4, Decimal("750")),
    )
    issues = detect_sku_typo_reviews(raw, items)
    assert "sku_typo_review:Widget A→WidgetA" in issues
    assert "sku_typo_review:Gadget X→GadgetX" in issues
    assert not any("Widget B" in i for i in issues)


def test_partition_sku_typo_issues() -> None:
    other, typo = partition_sku_typo_issues(
        ["unknown_item:X", "sku_typo_review:Widget A→WidgetA", "zero_stock:FakeItem"]
    )
    assert other == ["unknown_item:X", "zero_stock:FakeItem"]
    assert typo == ["sku_typo_review:Widget A→WidgetA"]


def test_stub_pipeline_1012_silent_space_normalize_pays(tmp_path: Path) -> None:
    """Spaced catalog labels (Widget A) auto-normalize; under-$10k pays without VP."""
    pipe = Pipeline(work_dir=tmp_path / "r", use_grok=False, profile="case")
    result = pipe.process_file(DATA / "invoice_1012.txt")
    assert result.status == "paid"
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-1012"]
    validated = next(e for e in events if e["event_type"] == "InvoiceValidated")
    soft = validated["payload"].get("soft_escalations") or []
    assert not any(str(i).startswith("sku_typo_review") for i in soft)
    items = validated["payload"]["invoice"]["items"]
    skus = {i["sku"] for i in items}
    assert "WidgetA" in skus and "GadgetX" in skus
