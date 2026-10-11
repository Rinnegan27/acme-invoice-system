"""Shared SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL and busy timeout.

    Parameters
    ----------
    db_path : str or Path
        Database file path.

    Returns
    -------
    sqlite3.Connection
        Configured connection with Row factory.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection, schema_path: str | Path) -> None:
    """Apply SQL schema file to the connection."""
    sql = Path(schema_path).read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
