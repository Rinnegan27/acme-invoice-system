"""High-value fraud eval harness (offline stub)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.llm_grok import (
    APPROVE_PROMPT_VERSION,
    EXTRACT_PROMPT_VERSION,
)
from invoice_automation.adapters.llm_stub import OfflineLLM
from invoice_automation.adapters.parsers import parse_invoice_text
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem

pytestmark = pytest.mark.black_box

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "evals" / "hv_fraud"


def _invoice(
    *,
    invoice_id: str,
    vendor: str,
    amount: str,
    items: list[LineItem],
    approval_reason: str = "",
) -> Invoice:
    return Invoice(
        invoice_id=invoice_id,
        vendor=vendor,
        amount=Decimal(amount),
        due_date=None,
        items=tuple(items),
        status=InvoiceStatus.VALIDATED,
        approval_reason=approval_reason,
        issues=(),
        source_path=f"eval:{invoice_id}",
        correlation_id="eval",
    )


def test_prompt_versions_pinned() -> None:
    assert EXTRACT_PROMPT_VERSION.startswith("extract-")
    assert APPROVE_PROMPT_VERSION.startswith("approve-")


def test_hv_clean_approves_with_reflection() -> None:
    llm = OfflineLLM()
    inv = _invoice(
        invoice_id="INV-HV-CLEAN",
        vendor="Acme Industrial Supplies",
        amount="15000.00",
        items=[
            LineItem(sku="WidgetA", quantity=40, unit_price=Decimal("250")),
            LineItem(sku="WidgetB", quantity=10, unit_price=Decimal("500")),
        ],
    )
    decision = llm.approve(inv)
    assert decision.approved is True
    assert decision.reflected is True


def test_hv_fakeitem_rejected() -> None:
    llm = OfflineLLM()
    path = EVAL_DIR / "hv_fakeitem.txt"
    parsed = parse_invoice_text(path.read_text(encoding="utf-8"), str(path))
    # Clear validation issues so approve path exercises VP reflection.
    inv = parsed.with_updates(status=InvoiceStatus.VALIDATED, issues=())
    assert inv.is_high_value
    decision = llm.approve(inv)
    assert decision.approved is False
    assert decision.reflected is True
    assert "suspicious" in decision.reason.lower() or "fake" in decision.reason.lower()


def test_hv_urgent_wire_rejected() -> None:
    llm = OfflineLLM()
    path = EVAL_DIR / "hv_urgent_wire.txt"
    parsed = parse_invoice_text(path.read_text(encoding="utf-8"), str(path))
    inv = parsed.with_updates(status=InvoiceStatus.VALIDATED, issues=())
    decision = llm.approve(inv)
    assert decision.approved is False
    assert decision.reflected is True
