"""CLI human approve / reject / escalate gate for VP-required invoices."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.cli_hitl import cli_human_gate_enabled, needs_human_or_vp_gate
from invoice_automation.domain.models import Invoice, LineItem
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box

HV_BODY = """\
Invoice Number: INV-HITL-HV
Vendor: Big Co
Item: WidgetA
Qty: 10
Unit Price: $250
Item: WidgetB
Qty: 8
Unit Price: $500
Item: GadgetX
Qty: 5
Unit Price: $750
Total: $10250
"""


def test_needs_gate_for_high_value_and_soft() -> None:
    hv = Invoice(
        invoice_id="INV-HV",
        vendor="V",
        amount=Decimal("15000"),
        due_date=date(2026, 2, 1),
        items=(LineItem("WidgetA", 1, Decimal("250")),),
        source_path="x.txt",
    )
    assert needs_human_or_vp_gate(hv)
    soft = Invoice(
        invoice_id="INV-S",
        vendor="V",
        amount=Decimal("250"),
        due_date=date(2026, 2, 1),
        items=(LineItem("WidgetA", 1, Decimal("250")),),
        source_path="x.txt",
        issues=("sku_typo_review:Widget Alpha→WidgetA",),
    )
    assert needs_human_or_vp_gate(soft)
    clean = Invoice(
        invoice_id="INV-C",
        vendor="V",
        amount=Decimal("250"),
        due_date=date(2026, 2, 1),
        items=(LineItem("WidgetA", 1, Decimal("250")),),
        source_path="x.txt",
    )
    assert not needs_human_or_vp_gate(clean)


def test_cli_human_gate_env_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_CLI_AUTO_VP", "1")
    assert cli_human_gate_enabled(force=None) is False
    assert cli_human_gate_enabled(force=False) is False
    assert cli_human_gate_enabled(force=True) is True  # --human-approval wins


def test_human_reject_via_cli_gate(tmp_path: Path) -> None:
    path = tmp_path / "hv.txt"
    path.write_text(HV_BODY, encoding="utf-8")
    pipe = Pipeline(
        work_dir=tmp_path / "rt",
        use_grok=False,
        profile="case",
        human_gate=lambda _inv: "reject",
    )
    result = pipe.process_file(path)
    assert result.status == "rejected"
    assert "Human rejected" in (result.approval_reason or "")
    events = pipe.events.read_all()
    assert any(e["event_type"] == "HumanApprovalGate" for e in events)
    gate = next(e for e in events if e["event_type"] == "HumanApprovalGate")
    assert gate["payload"]["action"] == "reject"


def test_human_approve_via_cli_gate(tmp_path: Path) -> None:
    path = tmp_path / "hv.txt"
    path.write_text(HV_BODY.replace("INV-HITL-HV", "INV-HITL-A"), encoding="utf-8")
    pipe = Pipeline(
        work_dir=tmp_path / "rt",
        use_grok=False,
        profile="case",
        human_gate=lambda _inv: "approve",
    )
    result = pipe.process_file(path)
    assert result.status == "paid"
    events = pipe.events.read_all()
    approved = next(e for e in events if e["event_type"] == "InvoiceApproved")
    assert approved["payload"].get("human") is True
    assert approved["payload"].get("actor") == "human_cli"


def test_escalate_uses_vp_agent(tmp_path: Path) -> None:
    path = tmp_path / "soft.txt"
    path.write_text(
        "Invoice Number: INV-HITL-E\nVendor: Alias Traders\nItem: Widget Alpha\n"
        "Qty: 1\nUnit Price: $250\nTotal: $250\n",
        encoding="utf-8",
    )
    pipe = Pipeline(
        work_dir=tmp_path / "rt",
        use_grok=False,
        profile="case",
        human_gate=lambda _inv: "escalate",
    )
    result = pipe.process_file(path)
    # Stub VP approves clear unique typo maps after reflection.
    assert result.status == "paid"
    gate = next(e for e in pipe.events.read_all() if e["event_type"] == "HumanApprovalGate")
    assert gate["payload"]["action"] == "escalate"
