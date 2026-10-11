"""Literal resources from the Galatiq case brief.

Source: https://github.com/galatiq-ai/galatiq-case-invoices

These helpers keep the APIs and seed data from the case README.
The submission matches the brief where the brief shows code.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Mock inventory database (required setup) — case README seed
# ---------------------------------------------------------------------------
INVENTORY_SEED: tuple[tuple[str, int], ...] = (
    ("WidgetA", 15),
    ("WidgetB", 10),
    ("GadgetX", 5),
    ("FakeItem", 0),
)

INVENTORY_SCHEMA_SQL = "CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)"

INVENTORY_INSERT_SQL = """
    INSERT INTO inventory VALUES
    ('WidgetA', 15),
    ('WidgetB', 10),
    ('GadgetX', 5),
    ('FakeItem', 0)
"""


def setup_inventory_db(db_path: str | Path = "inventory.db") -> Path:
    """Create the case-brief inventory database with the starter seed.

    This matches the case README snippet::

        import sqlite3
        conn = sqlite3.connect('inventory.db')
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)')
        cursor.execute(\"\"\"INSERT INTO inventory VALUES
            ('WidgetA', 15), ('WidgetB', 10), ('GadgetX', 5), ('FakeItem', 0)\"\"\")
        conn.commit()

    Parameters
    ----------
    db_path : str or Path
        Path to the SQLite file.

    Returns
    -------
    Path
        Path to the inventory file.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()
    cursor.execute(INVENTORY_SCHEMA_SQL)
    cursor.execute("DELETE FROM inventory")
    cursor.execute(INVENTORY_INSERT_SQL)
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Mock payment API — case README, verbatim
# ---------------------------------------------------------------------------
def mock_payment(vendor: Any, amount: Any) -> dict[str, str]:
    """Run the case-brief mock payment API.

    Parameters
    ----------
    vendor :
        Payee name.
    amount :
        Payment amount.

    Returns
    -------
    dict
        ``{"status": "success"}`` after the case log line prints.
    """
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Grok API setup — case README placeholder (your_key)
# Live client: adapters/llm_grok.py (OpenAI-compatible xAI API).
# ---------------------------------------------------------------------------
GROK_API_KEY_PLACEHOLDER = "your_key"
GROK_MODEL = "grok-3"
GROK_CASE_SNIPPET = (
    "from xai import Grok\n"
    "\n"
    'client = Grok(api_key="your_key")\n'
    "response = client.chat.completions.create(\n"
    '    model="grok-3",\n'
    '    messages=[{"role": "user", "content": "Reason about this..."}]\n'
    ")"
)

# Case CLI contract. Upstream data ships invoice_1001.txt (not invoice1.txt).
# This repo provides data/invoices/invoice1.txt as the brief entry alias.
CASE_CLI = "python main.py --invoice_path=data/invoices/invoice1.txt"

_PLACEHOLDER_KEYS = frozenset(
    {
        "",
        "your_key",
        "xai-your-key-here",
        "xai-...",
        "changeme",
        "replace-me",
    }
)


def is_live_xai_key(api_key: str | None) -> bool:
    """Return True only when a real xAI key is set.

    Parameters
    ----------
    api_key : str or None
        Value from the environment or prompt.

    Returns
    -------
    bool
        False for blank or placeholder keys.
    """
    if api_key is None:
        return False
    key = api_key.strip()
    if key in _PLACEHOLDER_KEYS:
        return False
    if "your-key" in key.lower() or key.endswith("..."):
        return False
    return bool(key)
