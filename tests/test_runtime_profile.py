"""GALATIQ_PROFILE master-data defaults."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.runtime_profile import resolve_master_data

pytestmark = pytest.mark.white_box


def test_prod_is_default_when_env_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GALATIQ_PROFILE", raising=False)
    flags = resolve_master_data()
    assert flags.profile == "prod"
    assert flags.require_price_check is True
    assert flags.require_po is True
    assert flags.soft_price_bands is False


def test_case_profile_soft_bands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_PROFILE", "case")
    flags = resolve_master_data()
    assert flags.profile == "case"
    assert flags.require_price_check is False
    assert flags.require_po is False
    assert flags.soft_price_bands is True


def test_pipeline_prod_rejects_catalog_discount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GALATIQ_PROFILE", "prod")
    pipe = Pipeline(work_dir=tmp_path / "prod", use_grok=False, profile="prod")
    # 200 is outside ±5% of catalog 250 (soft bands would still allow it).
    issues = pipe.inventory.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("200.00"))]
    )
    assert any(i.startswith("price_mismatch:WidgetA") for i in issues)
    assert pipe.inventory.require_po is True


def test_pipeline_case_allows_corpus_discount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GALATIQ_PROFILE", "case")
    pipe = Pipeline(work_dir=tmp_path / "case", use_grok=False, profile="case")
    issues = pipe.inventory.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("240.00"))]
    )
    assert not any(i.startswith("price_mismatch") for i in issues)
