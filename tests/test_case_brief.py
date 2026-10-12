"""Assert case-brief APIs / seed / CLI contract stay wired in."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_automation.adapters.payment_mock import MockPaymentGateway
from invoice_automation.adapters.sqlite_inventory import DEFAULT_SEED, SqliteInventoryRepository
from invoice_automation.case_brief import (
    CASE_CLI,
    GROK_API_KEY_PLACEHOLDER,
    GROK_CASE_SNIPPET,
    GROK_MODEL,
    INVENTORY_SEED,
    mock_payment,
    setup_inventory_db,
)
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"


def test_mock_payment_matches_case_brief(capsys) -> None:
    out = mock_payment("Widgets Inc.", 5000)
    assert out == {"status": "success"}
    captured = capsys.readouterr()
    assert "Paid 5000 to Widgets Inc." in captured.err
    assert "Paid" not in captured.out


def test_gateway_calls_case_mock_payment(capsys) -> None:
    gw = MockPaymentGateway()
    result = gw.pay("k1", "Acme", Decimal("12.50"))
    assert result.status == "success"
    captured = capsys.readouterr()
    assert "Paid 12.50 to Acme" in captured.err
    assert "Paid" not in captured.out


def test_inventory_seed_matches_case_readme(tmp_path: Path) -> None:
    assert INVENTORY_SEED == (
        ("WidgetA", 15),
        ("WidgetB", 10),
        ("GadgetX", 5),
        ("FakeItem", 0),
    )
    assert DEFAULT_SEED == INVENTORY_SEED
    path = setup_inventory_db(tmp_path / "inventory.db")
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT item, stock FROM inventory ORDER BY item").fetchall()
    conn.close()
    assert rows == [
        ("FakeItem", 0),
        ("GadgetX", 5),
        ("WidgetA", 15),
        ("WidgetB", 10),
    ]
    repo = SqliteInventoryRepository(tmp_path / "inv2.db")
    assert repo.check_availability([]) == []


def test_grok_placeholder_and_cli_contract() -> None:
    assert GROK_API_KEY_PLACEHOLDER == "your_key"
    assert GROK_MODEL == "grok-3"
    assert 'api_key="your_key"' in GROK_CASE_SNIPPET
    assert 'model="grok-3"' in GROK_CASE_SNIPPET
    assert CASE_CLI == "python main.py --invoice_path=data/invoices/invoice1.txt"
    assert (DATA / "invoice1.txt").is_file()
    assert (DATA / "invoice_1001.txt").is_file()


def test_case_cli_path_runs_end_to_end(tmp_path: Path, capsys) -> None:
    pipe = Pipeline(work_dir=tmp_path / "cli", use_grok=False, profile="case")
    result = pipe.process_file(DATA / "invoice1.txt")
    assert result.status == "paid"
    captured = capsys.readouterr()
    assert "Paid" in captured.err
    assert "Paid" not in captured.out
