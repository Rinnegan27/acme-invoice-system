"""Vendor velocity / split-invoice structuring checks."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from invoice_automation.adapters.sqlite_db import connect
from invoice_automation.domain.models import HIGH_VALUE_THRESHOLD
from invoice_automation.policy.invariants import VENDOR_SPLIT_RISK_PREFIX

# UAT window: multiple under-threshold invoices from one vendor in five minutes.
DEFAULT_SPLIT_WINDOW_S = 300.0


def detect_vendor_split_risk(
    vendor: str,
    amount: Decimal,
    *,
    db_path: str | Path | None,
    invoice_id: str = "",
    window_s: float = DEFAULT_SPLIT_WINDOW_S,
    threshold: Decimal = HIGH_VALUE_THRESHOLD,
) -> list[str]:
    """Flag under-threshold invoices that cumulate above the VP bar.

    Parameters
    ----------
    vendor : str
        Current invoice vendor.
    amount : Decimal
        Current invoice amount.
    db_path : path or None
        ``system.db`` with ``payment_intent`` history. None skips the check.
    invoice_id : str
        Current id (excluded from the prior sum).
    window_s : float
        Lookback window in seconds (default 300 = 5 minutes).
    threshold : Decimal
        Cumulative trigger (default ``HIGH_VALUE_THRESHOLD`` = $10k).

    Returns
    -------
    list of str
        Empty, or one ``vendor_split_risk:…`` finding for VP review.
    """
    if db_path is None:
        return []
    path = Path(db_path)
    if not path.exists():
        return []
    vendor_key = str(vendor or "").strip().lower()
    if not vendor_key or vendor_key == "unknown":
        return []

    cutoff = time.time() - float(window_s)
    prior = Decimal("0")
    peers: list[str] = []
    with connect(path) as conn:
        # Older DBs may lack payment_intent during first open — ignore.
        try:
            rows = conn.execute(
                """
                SELECT invoice_id, amount, status,
                       COALESCE(updated_at, created_at) AS ts
                FROM payment_intent
                WHERE lower(vendor) = ?
                  AND status IN ('SUCCEEDED', 'PENDING', 'RECONCILE')
                  AND COALESCE(updated_at, created_at) >= ?
                """,
                (vendor_key, cutoff),
            ).fetchall()
        except Exception:  # noqa: BLE001 — table may not exist yet
            return []

    for row in rows:
        peer_id = str(row["invoice_id"])
        if invoice_id and peer_id == invoice_id:
            continue
        prior += Decimal(str(row["amount"]))
        peers.append(peer_id)

    if prior <= 0:
        return []
    total = prior + Decimal(str(amount))
    if total <= threshold:
        return []
    peer_txt = ",".join(peers) if peers else "-"
    return [
        f"{VENDOR_SPLIT_RISK_PREFIX}:prior={prior}+current={amount}"
        f">threshold={threshold} peers={peer_txt}"
    ]
