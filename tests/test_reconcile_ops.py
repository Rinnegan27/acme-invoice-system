"""Pay/stock reconcile list, retry, and ack."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.sqlite_inventory import SqliteInventoryRepository
from invoice_automation.domain.exceptions import PaymentError
from invoice_automation.domain.models import LineItem, PaymentResult
from invoice_automation.saga.payment_saga import PaymentSaga
from invoice_automation.workbench.service import WorkbenchService

pytestmark = pytest.mark.white_box

SCHEMA = Path(__file__).resolve().parents[1] / "spike" / "schema.sql"


def _ok_gateway() -> object:
    class OkGateway:
        def pay(self, idempotency_key: str, vendor: str, amount: Decimal) -> PaymentResult:
            return PaymentResult(
                status="success",
                vendor=vendor,
                amount=amount,
                idempotency_key=idempotency_key,
                transaction_id="tx-recon",
            )

    return OkGateway()


def test_reconcile_retry_after_reseed(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    saga = PaymentSaga(tmp_path / "sys.db", SCHEMA, _ok_gateway(), inventory=inv)
    with pytest.raises(PaymentError, match="stock_reconcile_required"):
        saga.pay(
            invoice_id="INV-RECON",
            vendor="V",
            amount=Decimal("100"),
            correlation_id="c1",
            items=[LineItem(sku="WidgetA", quantity=100, unit_price=Decimal("250"))],
        )
    open_rows = saga.list_reconcile_intents()
    assert len(open_rows) == 1
    assert open_rows[0]["invoice_id"] == "INV-RECON"
    assert open_rows[0]["items"]

    # Ops restocks, then retry.
    from invoice_automation.adapters.sqlite_db import connect

    with connect(inv.db_path) as conn:
        conn.execute("UPDATE inventory SET stock = 200 WHERE item = 'WidgetA'")
        conn.commit()

    result = saga.retry_stock_decrement("INV-RECON")
    assert result.status == "success"
    assert saga.list_reconcile_intents() == []
    assert inv.stock_levels()["WidgetA"] == 100


def test_reconcile_ack_closes_without_stock(tmp_path: Path) -> None:
    inv = SqliteInventoryRepository(tmp_path / "inv.db")
    before = inv.stock_levels()["WidgetA"]
    saga = PaymentSaga(tmp_path / "sys.db", SCHEMA, _ok_gateway(), inventory=inv)
    with pytest.raises(PaymentError, match="stock_reconcile_required"):
        saga.pay(
            invoice_id="INV-ACK",
            vendor="V",
            amount=Decimal("50"),
            correlation_id="c2",
            items=[LineItem(sku="WidgetA", quantity=100, unit_price=Decimal("250"))],
        )
    saga.acknowledge_reconcile("INV-ACK", note="investigated offline")
    assert saga.list_reconcile_intents() == []
    assert inv.stock_levels()["WidgetA"] == before
    types = [r["event_type"] for r in saga.outbox_events()]
    assert "PaymentReconcileAcked" in types


def test_workbench_reconcile_surface(tmp_path: Path) -> None:
    svc = WorkbenchService(tmp_path / "wb", use_grok=False, profile="case")
    inv = svc.pipeline.inventory
    saga = svc.pipeline.saga
    with pytest.raises(PaymentError, match="stock_reconcile_required"):
        saga.pay(
            invoice_id="INV-WB",
            vendor="V",
            amount=Decimal("10"),
            correlation_id="c3",
            items=[LineItem(sku="WidgetA", quantity=100, unit_price=Decimal("250"))],
        )
    assert len(svc.list_reconcile()) == 1
    svc.acknowledge_reconcile("INV-WB", note="ops", actor_role="vp")
    assert svc.list_reconcile() == []
    assert inv.stock_levels()["WidgetA"] == 15
