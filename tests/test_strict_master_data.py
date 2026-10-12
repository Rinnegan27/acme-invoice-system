"""CLI / Pipeline strict catalog price mode."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box


def test_strict_master_data_flags_catalog_mismatch(tmp_path: Path) -> None:
    pipe = Pipeline(
        work_dir=tmp_path / "run",
        use_grok=False,
        require_price_check=True,
    )
    issues = pipe.inventory.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("200.00"))]
    )
    assert any(i.startswith("price_mismatch:WidgetA") for i in issues)


def test_case_profile_soft_bands_allow_corpus_discount(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "run2", use_grok=False, profile="case")
    issues = pipe.inventory.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("240.00"))]
    )
    assert not any(i.startswith("price_mismatch") for i in issues)
