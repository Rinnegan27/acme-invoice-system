"""SQLite inventory store that matches the Galatiq seed data."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from invoice_automation.adapters.sqlite_db import connect
from invoice_automation.case_brief import INVENTORY_SCHEMA_SQL, INVENTORY_SEED
from invoice_automation.domain.models import LineItem

# Case README seed. Kept as DEFAULT_SEED for clear call sites.
DEFAULT_SEED: tuple[tuple[str, int], ...] = INVENTORY_SEED


class SqliteInventoryRepository:
    """Check item stock in a local SQLite file."""

    def __init__(self, db_path: str | Path, *, reseeds: bool = True) -> None:
        self.db_path = Path(db_path)
        self._init_db(reseeds=reseeds)

    def _init_db(self, *, reseeds: bool) -> None:
        with connect(self.db_path) as conn:
            conn.execute(INVENTORY_SCHEMA_SQL)
            if reseeds:
                conn.execute("DELETE FROM inventory")
                conn.executemany(
                    "INSERT INTO inventory VALUES (?, ?)",
                    DEFAULT_SEED,
                )
            conn.commit()

    def check_availability(self, items: Sequence[LineItem]) -> list[str]:
        """Return issue codes for inventory / integrity problems.

        Returns
        -------
        list of str
            Empty when all items are available and quantities are valid.
        """
        issues: list[str] = []
        with connect(self.db_path) as conn:
            for item in items:
                if item.quantity <= 0:
                    issues.append(f"invalid_quantity:{item.sku}")
                    continue
                row = conn.execute(
                    "SELECT stock FROM inventory WHERE item = ?",
                    (item.sku,),
                ).fetchone()
                if row is None:
                    issues.append(f"unknown_item:{item.sku}")
                elif int(row["stock"]) == 0:
                    issues.append(f"zero_stock:{item.sku}")
                elif item.quantity > int(row["stock"]):
                    issues.append(f"insufficient_stock:{item.sku}")
        return issues
