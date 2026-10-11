"""Deterministic schema and integrity checks. No LLM work here."""

from __future__ import annotations

import re
from decimal import Decimal

from invoice_automation.domain.models import Invoice

_SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all",
    "system:",
    "assistant:",
    "<|",
    "you are now",
    "disregard",
)


def collect_invariant_issues(invoice: Invoice) -> list[str]:
    """Return hard integrity issue codes for one extracted invoice.

    Parameters
    ----------
    invoice : Invoice
        Invoice after extract.

    Returns
    -------
    list of str
        Issue codes. Empty when the invoice passes integrity checks.
    """
    issues: list[str] = []
    if invoice.amount < 0:
        issues.append("negative_amount")
    if not invoice.vendor or not invoice.vendor.strip() or invoice.vendor == "Unknown":
        issues.append("missing_vendor")
    vendor_l = (invoice.vendor or "").lower()
    if any(m in vendor_l for m in _INJECTION_MARKERS):
        issues.append("suspicious_vendor_text")

    priced = True
    line_total = Decimal("0")
    for item in invoice.items:
        if item.quantity <= 0:
            issues.append(f"invalid_quantity:{item.sku}")
        if not _SKU_RE.match(item.sku.strip()):
            issues.append(f"invalid_sku_charset:{item.sku}")
        if item.unit_price is None:
            priced = False
        else:
            if item.unit_price < 0:
                issues.append(f"negative_unit_price:{item.sku}")
            line_total += item.unit_price * item.quantity

    if priced and invoice.items and invoice.amount >= 0:
        # Lines exceeding total is an integrity / spatial-join fault.
        # Totals above lines are allowed (tax, shipping, fees) — common in the case corpus.
        if line_total > invoice.amount + Decimal("0.05"):
            issues.append("amount_line_mismatch")

    return issues
