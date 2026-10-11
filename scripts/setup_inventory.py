#!/usr/bin/env python3
"""Case-brief inventory setup (verbatim from galatiq-case-invoices README).

Usage
-----
python scripts/setup_inventory.py
python scripts/setup_inventory.py path/to/inventory.db
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("inventory.db")

    # --- begin case README snippet ---
    conn = sqlite3.connect(str(db_path))  # Persist to file so all agents can access it
    cursor = conn.cursor()

    cursor.execute("CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)")
    cursor.execute("DELETE FROM inventory")  # idempotent re-run; seed below is case-verbatim
    cursor.execute("""
        INSERT INTO inventory VALUES
        ('WidgetA', 15),
        ('WidgetB', 10),
        ('GadgetX', 5),
        ('FakeItem', 0)
    """)
    conn.commit()
    # --- end case README snippet ---

    print(f"Seeded {db_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
