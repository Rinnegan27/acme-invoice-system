"""Workbench ingest, override, escalate, VP approve, bulk."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.workbench.service import WorkbenchService

pytestmark = pytest.mark.black_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


@pytest.fixture
def svc(tmp_path: Path) -> WorkbenchService:
    return WorkbenchService(tmp_path / "wb", use_grok=False)


def test_ingest_creates_pending(svc: WorkbenchService) -> None:
    rec = svc.ingest_file(DATA / "invoice_1001.txt")
    assert rec.invoice_id == "INV-1001"
    assert rec.status in {"pending_review", "needs_override"}
    assert any(r.id == rec.id for r in svc.list_inbox())


def test_low_confidence_or_self_corrected_needs_override(svc: WorkbenchService) -> None:
    # Messy 1002 often self-corrects via stub normalization
    rec = svc.ingest_file(DATA / "invoice_1002.txt")
    assert rec.status in {"needs_override", "pending_review", "awaiting_vp"}
    assert rec.issues or rec.high_value or rec.needs_override


def test_override_and_revalidate(svc: WorkbenchService) -> None:
    rec = svc.ingest_file(DATA / "invoice_1008.txt")
    assert any(i.startswith("unknown_item") for i in rec.issues)
    updated = svc.apply_overrides(
        rec.id,
        invoice_id="INV-1008",
        vendor="NoProd Industries",
        amount="9900",
        due_date="2026-01-20",
        items_text="WidgetA,2,250\nWidgetB,1,500",
        analyst_notes="Corrected unknown SKUs to inventory items",
        actor_role="analyst",
    )
    assert not any(i.startswith("unknown_item") for i in updated.issues)
    assert updated.confidence == 1.0


def test_escalate_moves_to_vp_queue(svc: WorkbenchService) -> None:
    rec = svc.ingest_file(DATA / "invoice_1001.txt")
    esc = svc.escalate(rec.id, note="Please review vendor")
    assert esc.status == "awaiting_vp"
    assert esc.escalated
    assert any(r.id == esc.id for r in svc.list_vp_queue())


def test_analyst_cannot_pay_high_value(svc: WorkbenchService) -> None:
    rec = svc.ingest_file(DATA / "invoice_1003.txt")
    # Fraud high value — analyst pay should fail
    with pytest.raises(ValidationError):
        svc.analyst_submit_pay(rec.id)


def test_vp_approve_pays_clean(svc: WorkbenchService) -> None:
    rec = svc.ingest_file(DATA / "invoice_1001.txt")
    # Ensure clear path
    if rec.issues:
        rec = svc.apply_overrides(
            rec.id,
            invoice_id=rec.invoice_id,
            vendor=rec.vendor,
            amount=str(rec.amount),
            due_date=rec.due_date.isoformat() if rec.due_date else "",
            items_text="\n".join(
                f"{i['sku']},{i['quantity']},{i.get('unit_price') or ''}" for i in rec.items
            ),
            analyst_notes="ok",
        )
    esc = svc.escalate(rec.id)
    paid = svc.vp_approve_pay(esc.id, note="VP ok")
    assert paid.status == "paid"
    assert any(r.id == paid.id for r in svc.list_history())


def test_bulk_ingest_samples(svc: WorkbenchService) -> None:
    paths = [
        DATA / "invoice_1001.txt",
        DATA / "invoice_1004.json",
        DATA / "invoice_1006.csv",
    ]
    ok, errors = svc.ingest_many(paths)
    assert len(ok) == 3
    assert errors == []
    assert len(svc.list_inbox()) + len(svc.list_history()) + len(svc.list_vp_queue()) >= 3
