"""Inventory stock decrement and master-data price checks."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.sqlite_inventory import SqliteInventoryRepository
from invoice_automation.domain.exceptions import PaymentError, ValidationError
from invoice_automation.domain.models import LineItem
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.saga.payment_saga import PaymentSaga

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"
SCHEMA = Path(__file__).resolve().parents[1] / "spike" / "schema.sql"


def test_soft_price_band_flags_absurd_price(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    issues = inv.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("999.00"))]
    )
    assert any(i.startswith("price_mismatch:WidgetA") for i in issues)


def test_soft_price_band_allows_corpus_discount(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    issues = inv.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("240.00"))]
    )
    assert not any(i.startswith("price_mismatch") for i in issues)


def test_strict_price_check_vs_catalog(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(
        tmp_path / "inv.db", require_price_check=True, soft_price_bands=False
    )
    # 200 is outside 5% of catalog 250 (soft bands would still allow it).
    issues = inv.check_availability(
        [LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("200.00"))]
    )
    assert any(i.startswith("price_mismatch:WidgetA") for i in issues)


def test_decrement_stock_and_shortfall(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    inv.decrement_stock([LineItem(sku="WidgetA", quantity=10, unit_price=Decimal("250"))])
    levels = inv.stock_levels()
    assert levels["WidgetA"] == 5
    with pytest.raises(ValidationError):
        inv.decrement_stock([LineItem(sku="WidgetA", quantity=10, unit_price=Decimal("250"))])


def test_failed_gateway_leaves_stock(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    before = inv.stock_levels()["WidgetA"]

    class BoomGateway:
        def pay(self, idempotency_key: str, vendor: str, amount: Decimal):
            raise RuntimeError("gateway down")

    saga = PaymentSaga(tmp_path / "sys.db", SCHEMA, BoomGateway(), inventory=inv)
    with pytest.raises(PaymentError):
        saga.pay(
            invoice_id="INV-X",
            vendor="V",
            amount=Decimal("100"),
            correlation_id="c1",
            items=[LineItem(sku="WidgetA", quantity=1, unit_price=Decimal("250"))],
        )
    assert inv.stock_levels()["WidgetA"] == before


def test_stock_fail_after_pay_marks_reconcile(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")

    class OkGateway:
        def pay(self, idempotency_key: str, vendor: str, amount: Decimal):
            from invoice_automation.domain.models import PaymentResult

            return PaymentResult(
                status="success",
                vendor=vendor,
                amount=amount,
                idempotency_key=idempotency_key,
                transaction_id="tx-1",
            )

    saga = PaymentSaga(tmp_path / "sys.db", SCHEMA, OkGateway(), inventory=inv)
    # Force shortfall: ask for more WidgetA than seed.
    with pytest.raises(PaymentError, match="stock_reconcile_required"):
        saga.pay(
            invoice_id="INV-RECON",
            vendor="V",
            amount=Decimal("100"),
            correlation_id="c-recon",
            items=[LineItem(sku="WidgetA", quantity=100, unit_price=Decimal("250"))],
        )
    rows = saga.outbox_events()
    assert any(r["event_type"] == "PaymentStockReconcile" for r in rows)
    assert inv.stock_levels()["WidgetA"] == 15


def test_pipeline_pay_decrements_stock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod")
    pipe = Pipeline(work_dir=tmp_path / "run", use_grok=False)
    before = pipe.inventory.stock_levels()
    result = pipe.process_file(DATA / "invoice_1001.txt")
    assert result.status == "paid"
    after = pipe.inventory.stock_levels()
    assert after["WidgetA"] == before["WidgetA"] - 10
    assert after["WidgetB"] == before["WidgetB"] - 5
