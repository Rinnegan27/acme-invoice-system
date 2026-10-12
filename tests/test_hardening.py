"""Guards for pipeline hardening nits (fail-closed parsers, permit secret, no core/)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.parsers import parse_invoice_text
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import StageName
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.engine import PolicyError, resolve_permit_secret

pytestmark = pytest.mark.white_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"


def test_core_package_must_not_exist() -> None:
    assert not (ROOT / "core").exists(), "dead legacy package core/ must stay deleted"


def test_text_invoice_missing_total_computes_from_unit_prices() -> None:
    raw = """INVOICE
Vendor: Widgets Inc.
Invoice Number: INV-NO-TOTAL
Items:
  WidgetA    qty: 2    unit price: $250.00
"""
    inv = parse_invoice_text(raw, "missing_total.txt")
    assert inv.amount == Decimal("500.00")
    assert inv.items[0].unit_price == Decimal("250.00")


def test_example_permit_secrets_rejected() -> None:
    with pytest.raises(PolicyError):
        resolve_permit_secret("local-dev-secret-replace-before-share")
    with pytest.raises(PolicyError):
        resolve_permit_secret("short")
    with pytest.raises(PolicyError):
        resolve_permit_secret("")


def test_tabular_csv_unpriced_without_total_fails() -> None:
    raw = """Invoice Number,Vendor,Item,Qty,Unit Price
INV-BAD,Acme,WidgetA,2,
"""
    with pytest.raises(ExtractionError, match="invalid_amount"):
        parse_invoice_text(raw, "bad.csv")


def test_drain_budget_exceeded_emits_event(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "budget", use_grok=False, max_steps=1)
    # Enqueue two invoices so one drain step cannot finish the backlog.
    pipe.enqueue_file(DATA / "invoice_1001.txt")
    pipe.enqueue_file(DATA / "invoice_1004.json")
    assert pipe.queue.depth(StageName.INGESTION) >= 2
    pipe.drain(max_steps=1)
    events = [e for e in pipe.events.read_all() if e.get("event_type") == "DrainBudgetExceeded"]
    assert events, "expected DrainBudgetExceeded when backlog remains after max_steps"
    assert events[0]["payload"]["queue_depth"] >= 1
    assert "DrainBudgetExceeded" in str(pipe.metrics.snapshot()["errors"])
