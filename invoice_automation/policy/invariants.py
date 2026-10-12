"""Schema and integrity checks. No LLM work.

Notes
-----
This module is not an ERP tax engine. When all lines have prices, a total
above the line sum is allowed for tax or fees. A total below the line sum
by more than $0.05 raises ``amount_line_mismatch``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from invoice_automation.domain.models import Invoice, LineItem

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

# Spaced catalog forms that extractors often "fix" into compact SKUs.
# When the source shows the spaced form and the extract returns the compact
# SKU, raise ``sku_typo_review`` so VP decides instead of silent auto-pay.
_SKU_SPACE_TYPOS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("WidgetA", re.compile(r"\bWidget\s+A\b", re.IGNORECASE), "Widget A"),
    ("WidgetB", re.compile(r"\bWidget\s+B\b", re.IGNORECASE), "Widget B"),
    ("GadgetX", re.compile(r"\bGadget\s+X\b", re.IGNORECASE), "Gadget X"),
)

SKU_TYPO_REVIEW_PREFIX = "sku_typo_review"
VENDOR_SPLIT_RISK_PREFIX = "vendor_split_risk"

# Soft findings that escalate to VP instead of hard-reject or silent auto-pay.
SOFT_ESCALATION_PREFIXES: tuple[str, ...] = (
    SKU_TYPO_REVIEW_PREFIX,
    VENDOR_SPLIT_RISK_PREFIX,
)


def is_sku_typo_review(issue: str) -> bool:
    """Return True when the issue is a soft SKU typo escalation."""
    return str(issue).startswith(SKU_TYPO_REVIEW_PREFIX)


def is_vendor_split_risk(issue: str) -> bool:
    """Return True when the issue is a vendor split / structuring risk."""
    return str(issue).startswith(VENDOR_SPLIT_RISK_PREFIX)


def is_soft_escalation(issue: str) -> bool:
    """Return True for soft findings that require VP review."""
    text = str(issue)
    return any(text.startswith(prefix) for prefix in SOFT_ESCALATION_PREFIXES)


def detect_sku_typo_reviews(raw_text: str, items: Sequence[LineItem]) -> list[str]:
    """Flag compact SKUs that look like spaced-source typo corrections.

    Parameters
    ----------
    raw_text : str
        Original invoice document text.
    items : sequence of LineItem
        Extracted line items (often already compacted by LLM/parser).

    Returns
    -------
    list of str
        Issue codes such as ``sku_typo_review:Widget A→WidgetA``.
    """
    raw = raw_text or ""
    present = {item.sku for item in items}
    issues: list[str] = []
    for compact, pattern, spaced in _SKU_SPACE_TYPOS:
        if compact in present and pattern.search(raw):
            issues.append(f"{SKU_TYPO_REVIEW_PREFIX}:{spaced}→{compact}")
    return issues


def partition_soft_escalation_issues(
    issues: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Split issues into (other, soft_escalation)."""
    soft: list[str] = []
    other: list[str] = []
    for issue in issues:
        if is_soft_escalation(issue):
            soft.append(issue)
        else:
            other.append(issue)
    return other, soft


def partition_sku_typo_issues(issues: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split issues into (other, soft escalation). Alias for callers."""
    return partition_soft_escalation_issues(issues)


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

    Notes
    -----
    When all lines have prices, a total above the line sum is allowed for
    tax or fees. A total below the line sum by more than $0.05 raises
    ``amount_line_mismatch``.
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
        # Line sum above total fails integrity.
        # Total above lines is allowed for tax, shipping, or fees.
        if line_total > invoice.amount + Decimal("0.05"):
            issues.append("amount_line_mismatch")

    return issues
