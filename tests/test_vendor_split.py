"""Vendor split / structuring detection across under-threshold invoices."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.vendor_risk import detect_vendor_split_risk

pytestmark = pytest.mark.white_box


def _write_split(path: Path, invoice_id: str, amount: str = "4000.00") -> None:
    # 8×250 + 4×500 = 4000 — within seed stock for a single invoice.
    path.write_text(
        f"""INVOICE
Vendor: SplitCo Fraud LLC
Invoice Number: {invoice_id}
Due Date: 2026-03-20
Items:
  WidgetA    qty: 8    unit price: $250.00
  WidgetB    qty: 4    unit price: $500.00
Total: ${amount}
""",
        encoding="utf-8",
    )


def test_detect_vendor_split_risk_helper(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    inv = tmp_path / "rt" / "inventory.db"
    # Boost stock so history can accumulate three pays if detection were absent.
    import sqlite3

    with sqlite3.connect(inv) as conn:
        conn.execute("UPDATE inventory SET stock = 200")
        conn.commit()

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    c = tmp_path / "c.txt"
    _write_split(a, "INV-200A")
    _write_split(b, "INV-200B")
    _write_split(c, "INV-200C")

    r1 = pipe.process_file(a)
    assert r1.status == "paid"
    assert (
        detect_vendor_split_risk(
            "SplitCo Fraud LLC",
            Decimal("4000"),
            db_path=tmp_path / "rt" / "system.db",
            invoice_id="INV-200B",
        )
        == []
    )  # 4k+4k = 8k still under 10k

    r2 = pipe.process_file(b)
    assert r2.status == "paid"
    risks = detect_vendor_split_risk(
        "SplitCo Fraud LLC",
        Decimal("4000"),
        db_path=tmp_path / "rt" / "system.db",
        invoice_id="INV-200C",
    )
    assert risks and risks[0].startswith("vendor_split_risk:")

    r3 = pipe.process_file(c)
    assert r3.status == "rejected"
    assert "split" in (r3.approval_reason or "").lower() or any(
        str(i).startswith("vendor_split_risk") for i in r3.issues
    )
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-200C"]
    validated = next(e for e in events if e["event_type"] == "InvoiceValidated")
    soft = validated["payload"].get("soft_escalations") or []
    assert any(str(i).startswith("vendor_split_risk") for i in soft)
    assert not any(e["event_type"] == "InvoiceApproved" for e in events)
    assert any(e["event_type"] == "InvoiceRejected" for e in events)
