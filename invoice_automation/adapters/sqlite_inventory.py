"""SQLite inventory store with stock, unit-price catalog, and PO lines."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from invoice_automation.adapters.sqlite_db import connect
from invoice_automation.case_brief import INVENTORY_SCHEMA_SQL, INVENTORY_SEED
from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.domain.models import LineItem

# Case README seed. Kept as DEFAULT_SEED for clear call sites.
DEFAULT_SEED: tuple[tuple[str, int], ...] = INVENTORY_SEED

# Catalog unit prices for master-data checks (5% tolerance by default).
DEFAULT_UNIT_PRICES: tuple[tuple[str, str], ...] = (
    ("WidgetA", "250.00"),
    ("WidgetB", "500.00"),
    ("GadgetX", "100.00"),
    ("FakeItem", "1.00"),
)

# Open PO coverage for happy-path SKUs (optional master-data check).
DEFAULT_PO_LINES: tuple[tuple[str, str, int], ...] = (
    ("PO-1001", "WidgetA", 50),
    ("PO-1001", "WidgetB", 50),
    ("PO-1001", "GadgetX", 20),
)

PRICE_TOLERANCE = Decimal("0.05")

UNIT_PRICE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS unit_prices (
    item TEXT PRIMARY KEY,
    unit_price TEXT NOT NULL
)
"""

PO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id TEXT NOT NULL,
    item TEXT NOT NULL,
    ordered_qty INTEGER NOT NULL,
    PRIMARY KEY (po_id, item)
)
"""


class SqliteInventoryRepository:
    """Check stock, unit prices, and PO coverage in a local SQLite file."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        reseeds: bool = True,
        price_tolerance: Decimal = PRICE_TOLERANCE,
        require_po: bool = False,
        require_price_check: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.price_tolerance = price_tolerance
        self.require_po = require_po
        # Off by default: case corpus unit prices vary; enable in master-data tests.
        self.require_price_check = require_price_check
        self._init_db(reseeds=reseeds)

    def _init_db(self, *, reseeds: bool) -> None:
        with connect(self.db_path) as conn:
            conn.execute(INVENTORY_SCHEMA_SQL)
            conn.execute(UNIT_PRICE_SCHEMA_SQL)
            conn.execute(PO_SCHEMA_SQL)
            if reseeds:
                self._reseed_conn(conn)
            conn.commit()

    def reseed(self) -> None:
        """Restore case-brief stock, prices, and PO seed data."""
        with connect(self.db_path) as conn:
            self._reseed_conn(conn)
            conn.commit()

    def _reseed_conn(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM inventory")
        conn.executemany("INSERT INTO inventory VALUES (?, ?)", DEFAULT_SEED)
        conn.execute("DELETE FROM unit_prices")
        conn.executemany("INSERT INTO unit_prices VALUES (?, ?)", DEFAULT_UNIT_PRICES)
        conn.execute("DELETE FROM purchase_orders")
        conn.executemany(
            "INSERT INTO purchase_orders (po_id, item, ordered_qty) VALUES (?, ?, ?)",
            DEFAULT_PO_LINES,
        )

    def stock_levels(self) -> dict[str, int]:
        """Return current stock map for tests."""
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT item, stock FROM inventory").fetchall()
            return {str(r["item"]): int(r["stock"]) for r in rows}

    def check_availability(self, items: Sequence[LineItem]) -> list[str]:
        """Return issue codes for inventory / integrity problems.

        Returns
        -------
        list of str
            Empty when all items are available and quantities are valid.

        Notes
        -----
        Quantities are summed by SKU so split lines cannot oversell stock.
        """
        issues: list[str] = []
        qty_by_sku: dict[str, int] = {}
        priced: dict[str, Decimal] = {}
        for item in items:
            if item.quantity <= 0:
                issues.append(f"invalid_quantity:{item.sku}")
                continue
            qty_by_sku[item.sku] = qty_by_sku.get(item.sku, 0) + item.quantity
            if item.unit_price is not None:
                priced[item.sku] = item.unit_price

        with connect(self.db_path) as conn:
            for sku, qty in qty_by_sku.items():
                row = conn.execute(
                    "SELECT stock FROM inventory WHERE item = ?",
                    (sku,),
                ).fetchone()
                if row is None:
                    issues.append(f"unknown_item:{sku}")
                elif int(row["stock"]) == 0:
                    issues.append(f"zero_stock:{sku}")
                elif qty > int(row["stock"]):
                    issues.append(f"insufficient_stock:{sku}")

                if self.require_price_check and sku in priced and priced[sku] >= 0:
                    price_row = conn.execute(
                        "SELECT unit_price FROM unit_prices WHERE item = ?",
                        (sku,),
                    ).fetchone()
                    if price_row is not None:
                        catalog = Decimal(str(price_row["unit_price"]))
                        if catalog > 0:
                            delta = abs(priced[sku] - catalog) / catalog
                            if delta > self.price_tolerance:
                                issues.append(f"price_mismatch:{sku}")

                if self.require_po:
                    po = conn.execute(
                        "SELECT ordered_qty FROM purchase_orders WHERE item = ?",
                        (sku,),
                    ).fetchone()
                    if po is None:
                        issues.append(f"no_po_match:{sku}")
                    elif qty > int(po["ordered_qty"]):
                        issues.append(f"po_qty_exceeded:{sku}")
        return issues

    def decrement_stock(self, items: Sequence[LineItem]) -> None:
        """Decrement stock atomically after a successful payment.

        Raises
        ------
        ValidationError
            When any SKU cannot be decremented (shortfall or unknown SKU).
        """
        qty_by_sku: dict[str, int] = {}
        for item in items:
            if item.quantity <= 0:
                continue
            qty_by_sku[item.sku] = qty_by_sku.get(item.sku, 0) + item.quantity

        with connect(self.db_path) as conn:
            try:
                for sku, qty in qty_by_sku.items():
                    cur = conn.execute(
                        """
                        UPDATE inventory
                        SET stock = stock - ?
                        WHERE item = ? AND stock >= ?
                        """,
                        (qty, sku, qty),
                    )
                    if cur.rowcount != 1:
                        raise ValidationError(f"stock_decrement_failed:{sku}:need={qty}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
