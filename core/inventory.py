from __future__ import annotations

import sqlite3
from typing import Sequence

from models import LineItem


class Inventory:
    def __init__(self, db_path: str = "inventory.db") -> None:
        self.db_path = db_path
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)"
            )
            conn.execute("DELETE FROM inventory")
            conn.executemany(
                "INSERT INTO inventory VALUES (?, ?)",
                [
                    ("WidgetA", 15),
                    ("WidgetB", 10),
                    ("GadgetX", 5),
                    ("FakeItem", 0),
                ],
            )
            conn.commit()

    def check(self, items: Sequence[LineItem]) -> list[str]:
        """Return list of issue strings. Empty list = valid."""
        issues = []
        with sqlite3.connect(self.db_path) as conn:
            for item in items:
                row = conn.execute(
                    "SELECT stock FROM inventory WHERE item = ?", (item.sku,)
                ).fetchone()
                if row is None:
                    issues.append(f"unknown_item:{item.sku}")
                elif item.quantity > row[0]:
                    issues.append(f"insufficient_stock:{item.sku}")
                elif row[0] == 0:
                    issues.append(f"zero_stock:{item.sku}")
        return issues
