"""SQLite inventory store with stock, unit-price bands, and PO lines."""

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

# Exact catalog for strict mode.
DEFAULT_UNIT_PRICES: tuple[tuple[str, str], ...] = (
    ("WidgetA", "250.00"),
    ("WidgetB", "500.00"),
    ("GadgetX", "100.00"),
    ("FakeItem", "1.00"),
)

# Soft bands allow corpus discounts and expedited prices.
DEFAULT_PRICE_BANDS: tuple[tuple[str, str, str], ...] = (
    ("WidgetA", "200.00", "300.00"),
    ("WidgetB", "400.00", "600.00"),
    ("GadgetX", "50.00", "800.00"),
    ("FakeItem", "0.01", "50000.00"),
)

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

PRICE_BAND_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS unit_price_bands (
    item TEXT PRIMARY KEY,
    min_price TEXT NOT NULL,
    max_price TEXT NOT NULL
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
    """Check stock, unit prices, and PO coverage in a local SQLite file.

    Parameters
    ----------
    db_path : str or Path
        SQLite inventory database path.
    reseeds : bool
        When True, restore seed stock and master data on open.
    price_tolerance : Decimal
        Max relative delta for strict catalog checks (default 0.05).
    require_po : bool
        When True, require a PO line that covers each SKU quantity.
    require_price_check : bool
        When True, compare unit price to the exact catalog within
        ``price_tolerance``. Off by default.
    soft_price_bands : bool
        When True and strict check is off, flag prices outside seed bands.
        On by default.

    Notes
    -----
    Soft band hits raise ``price_mismatch`` as a soft policy finding.
    Strict catalog and PO checks stay opt-in so the case corpus can pay.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        reseeds: bool = True,
        price_tolerance: Decimal = PRICE_TOLERANCE,
        require_po: bool = False,
        require_price_check: bool = False,
        soft_price_bands: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.price_tolerance = price_tolerance
        self.require_po = require_po
        # Strict catalog percent check. Off by default.
        self.require_price_check = require_price_check
        # Soft band check when unit_price is set. On by default.
        self.soft_price_bands = soft_price_bands
        self._init_db(reseeds=reseeds)

    def _init_db(self, *, reseeds: bool) -> None:
        # Create tables. Optionally reseed stock, prices, bands, and POs.
        with connect(self.db_path) as conn:
            conn.execute(INVENTORY_SCHEMA_SQL)
            conn.execute(UNIT_PRICE_SCHEMA_SQL)
            conn.execute(PRICE_BAND_SCHEMA_SQL)
            conn.execute(PO_SCHEMA_SQL)
            if reseeds:
                self._reseed_conn(conn)
            conn.commit()

    def reseed(self) -> None:
        # Restore case-brief stock, prices, bands, and PO seed data.
        with connect(self.db_path) as conn:
            self._reseed_conn(conn)
            conn.commit()

    def _reseed_conn(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM inventory")
        conn.executemany("INSERT INTO inventory VALUES (?, ?)", DEFAULT_SEED)
        conn.execute("DELETE FROM unit_prices")
        conn.executemany("INSERT INTO unit_prices VALUES (?, ?)", DEFAULT_UNIT_PRICES)
        conn.execute("DELETE FROM unit_price_bands")
        conn.executemany(
            "INSERT INTO unit_price_bands VALUES (?, ?, ?)",
            DEFAULT_PRICE_BANDS,
        )
        conn.execute("DELETE FROM purchase_orders")
        conn.executemany(
            "INSERT INTO purchase_orders (po_id, item, ordered_qty) VALUES (?, ?, ?)",
            DEFAULT_PO_LINES,
        )

    def stock_levels(self) -> dict[str, int]:
        # Current SKU → stock map (tests and demos).
        with connect(self.db_path) as conn:
            rows = conn.execute("SELECT item, stock FROM inventory").fetchall()
            return {str(r["item"]): int(r["stock"]) for r in rows}

    def check_availability(self, items: Sequence[LineItem]) -> list[str]:
        """Return issue codes for inventory and master-data problems.

        Parameters
        ----------
        items : sequence of LineItem
            Lines to check. Quantities are summed by SKU.

        Returns
        -------
        list of str
            Issue codes. Empty when stock and optional price/PO checks pass.

        Notes
        -----
        Sum quantities by SKU so split lines cannot oversell stock.
        Soft price-band mismatches are soft findings (see PolicyEngine).
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

                if sku in priced and priced[sku] >= 0:
                    if self.require_price_check:
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
                    elif self.soft_price_bands:
                        band = conn.execute(
                            "SELECT min_price, max_price FROM unit_price_bands WHERE item = ?",
                            (sku,),
                        ).fetchone()
                        if band is not None:
                            lo = Decimal(str(band["min_price"]))
                            hi = Decimal(str(band["max_price"]))
                            if priced[sku] < lo or priced[sku] > hi:
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

        Parameters
        ----------
        items : sequence of LineItem
            Lines to draw. Quantities are summed by SKU.

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
