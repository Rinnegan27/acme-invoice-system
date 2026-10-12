"""Same invoice_id: format-twin dedupe vs revision line/amount updates."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.payment_mock import MockPaymentGateway
from invoice_automation.adapters.sqlite_inventory import SqliteInventoryRepository
from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.policy.engine import invoice_payload_hash
from invoice_automation.saga.payment_saga import PaymentSaga

pytestmark = pytest.mark.white_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"
SCHEMA = ROOT / "spike" / "schema.sql"


def test_payload_hash_ignores_source_path() -> None:
    items = [{"sku": "WidgetA", "quantity": 3, "unit_price": "250"}]
    a = invoice_payload_hash(invoice_id="INV-1004", vendor="X", amount=Decimal("1890"), items=items)
    b = invoice_payload_hash(invoice_id="INV-1004", vendor="X", amount="1890.00", items=items)
    assert a == b


def test_format_twin_dedupes_without_second_stock_draw(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    first = pipe.process_file(DATA / "invoice_1011.txt")
    stock_after_first = pipe.inventory.stock_levels()
    second = pipe.process_file(DATA / "invoice_1011.pdf")
    assert first.status == "paid"
    assert second.status == "paid"
    assert pipe.inventory.stock_levels() == stock_after_first
    with sqlite3.connect(tmp_path / "rt" / "system.db") as conn:
        rows = conn.execute(
            "SELECT amount, status FROM payment_intent WHERE invoice_id='INV-1011'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "SUCCEEDED"


def test_1004_revision_updates_amount_and_stock_delta(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    first = pipe.process_file(DATA / "invoice_1004.json")
    assert first.status == "paid"
    stock_mid = pipe.inventory.stock_levels()
    second = pipe.process_file(DATA / "invoice_1004_revised.json")
    assert second.status == "paid"
    stock_end = pipe.inventory.stock_levels()
    # Revised adds GadgetX qty 5 — only that SKU should drop further.
    assert stock_end["GadgetX"] == stock_mid["GadgetX"] - 5
    assert stock_end["WidgetA"] == stock_mid["WidgetA"]
    assert stock_end["WidgetB"] == stock_mid["WidgetB"]
    with sqlite3.connect(tmp_path / "rt" / "system.db") as conn:
        row = conn.execute(
            "SELECT amount, items_json FROM payment_intent WHERE invoice_id='INV-1004'"
        ).fetchone()
    assert Decimal(row[0]) == Decimal("5940.00") or Decimal(row[0]) == Decimal("5940")
    items = json.loads(row[1])
    skus = {i["sku"] for i in items}
    assert "GadgetX" in skus
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-1004"]
    assert any(e["event_type"] == "PaymentRevised" for e in events)


def test_qty_increase_revision_under_tight_stock(tmp_path: Path) -> None:
    """WidgetA 3→4 only needs +1 on the shelf — validation must credit prior draw."""
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    # Drain WidgetA to 1 left after a synthetic first pay of qty 3.
    pipe.inventory.decrement_stock(
        [
            LineItem("WidgetA", 11, Decimal("250")),
            LineItem("WidgetB", 2, Decimal("500")),
        ]
    )
    # Seed payment_intent as if INV-QTY was already paid for WidgetA×3.
    first = pipe.saga.pay(
        invoice_id="INV-QTY",
        vendor="Precision Parts Ltd.",
        amount=Decimal("810"),
        correlation_id="c-first",
        items=(LineItem("WidgetA", 3, Decimal("250")),),
    )
    assert first.status == "success"
    assert pipe.inventory.stock_levels()["WidgetA"] == 1  # 15-11-3

    # Write a revised invoice file: same id, WidgetA 3→4.
    rev = tmp_path / "inv_qty_rev.json"
    rev.write_text(
        json.dumps(
            {
                "invoice_number": "INV-QTY",
                "vendor": {"name": "Precision Parts Ltd."},
                "date": "2026-01-22",
                "due_date": "2026-02-22",
                "line_items": [
                    {"item": "WidgetA", "quantity": 4, "unit_price": 250.00},
                ],
                "subtotal": 1000.00,
                "tax_rate": 0.08,
                "tax_amount": 80.00,
                "total": 1080.00,
                "currency": "USD",
            }
        ),
        encoding="utf-8",
    )
    second = pipe.process_file(rev)
    assert second.status == "paid"
    assert pipe.inventory.stock_levels()["WidgetA"] == 0  # drew the +1 delta


def test_saga_revision_delta_pay_unit(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    saga = PaymentSaga(
        tmp_path / "sys.db",
        SCHEMA,
        MockPaymentGateway(),
        inventory=inv,
    )
    items1 = (
        LineItem("WidgetA", 3, Decimal("250")),
        LineItem("WidgetB", 2, Decimal("500")),
    )
    r1 = saga.pay(
        invoice_id="INV-1004",
        vendor="Precision Parts Ltd.",
        amount=Decimal("1890"),
        correlation_id="c1",
        items=items1,
    )
    assert r1.revision is False
    items2 = items1 + (LineItem("GadgetX", 5, Decimal("750")),)
    r2 = saga.pay(
        invoice_id="INV-1004",
        vendor="Precision Parts Ltd.",
        amount=Decimal("5940"),
        correlation_id="c2",
        items=items2,
    )
    assert r2.revision is True
    assert r2.amount == Decimal("5940")
    assert inv.stock_levels()["GadgetX"] == 0  # seed 5, drew 5
