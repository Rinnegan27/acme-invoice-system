"""Tax and fee total rules. Not a full tax engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem
from invoice_automation.policy.invariants import collect_invariant_issues

pytestmark = pytest.mark.white_box


def test_total_above_lines_allowed_for_tax() -> None:
    inv = Invoice(
        invoice_id="INV-TAX",
        vendor="Acme",
        amount=Decimal("110.00"),
        due_date=None,
        items=(LineItem("WidgetA", 1, Decimal("100.00")),),
        source_path="tax.txt",
        status=InvoiceStatus.EXTRACTED,
        issues=(),
        correlation_id="t1",
    )
    assert "amount_line_mismatch" not in collect_invariant_issues(inv)


def test_total_below_lines_flagged() -> None:
    inv = Invoice(
        invoice_id="INV-LOW",
        vendor="Acme",
        amount=Decimal("50.00"),
        due_date=None,
        items=(LineItem("WidgetA", 1, Decimal("100.00")),),
        source_path="low.txt",
        status=InvoiceStatus.EXTRACTED,
        issues=(),
        correlation_id="t2",
    )
    assert "amount_line_mismatch" in collect_invariant_issues(inv)
