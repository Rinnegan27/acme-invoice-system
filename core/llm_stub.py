from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, List, Optional, Tuple

from models import Invoice, LineItem, InvoiceStatus


class OfflineLLM:
    """Deterministic, improved extractor for Galatiq sample formats."""

    def extract(self, raw_text: str, source_path: str) -> Invoice:
        suffix = Path(source_path).suffix.lower()

        if suffix == ".json":
            return self._from_json(raw_text, source_path)
        if suffix == ".csv":
            return self._from_csv(raw_text, source_path)

        return self._from_text(raw_text, source_path)

    def approve(self, invoice: Invoice) -> Tuple[bool, str]:
        if invoice.amount > Decimal("10000") and invoice.issues:
            return False, f"High value ({invoice.amount}) with issues: {invoice.issues}"
        if invoice.amount > Decimal("10000"):
            return True, "High value approved after scrutiny"
        return True, "Auto-approved under threshold"

    def _from_json(self, raw: str, source_path: str) -> Invoice:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._from_text(raw, source_path)

        invoice_id = str(data.get("invoice_id") or data.get("id") or Path(source_path).stem)
        vendor = str(data.get("vendor") or data.get("supplier") or "Unknown")
        amount = self._to_decimal(data.get("amount") or data.get("total") or 0)

        items = []
        for item in data.get("items") or data.get("line_items") or []:
            sku = str(item.get("sku") or item.get("item") or item.get("name") or "UNKNOWN")
            qty = int(item.get("quantity") or item.get("qty") or 1)
            price = self._to_decimal(item.get("unit_price") or item.get("price"))
            items.append(LineItem(sku=sku, quantity=qty, unit_price=price))

        if not items:
            items = [LineItem(sku="UNKNOWN", quantity=1)]

        return Invoice(
            invoice_id=invoice_id,
            vendor=vendor,
            amount=amount,
            due_date=None,
            items=tuple(items),
            source_path=source_path,
            status=InvoiceStatus.EXTRACTED,
        )

    def _from_csv(self, raw: str, source_path: str) -> Invoice:
        lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        if not lines:
            return self._empty(source_path)

        header = [c.strip().lower() for c in lines[0].split(",")]
        data_row = lines[1].split(",") if len(lines) > 1 else []

        def col(name: str, default: str = "") -> str:
            try:
                idx = header.index(name)
                return data_row[idx].strip() if idx < len(data_row) else default
            except ValueError:
                return default

        invoice_id = col("invoice_id") or col("id") or Path(source_path).stem
        vendor = col("vendor") or col("supplier") or "Unknown"
        amount = self._to_decimal(col("amount") or col("total") or "0")
        sku = col("item") or col("sku") or "UNKNOWN"
        qty = int(col("quantity") or col("qty") or "1")

        return Invoice(
            invoice_id=invoice_id,
            vendor=vendor,
            amount=amount,
            due_date=None,
            items=(LineItem(sku=sku, quantity=qty),),
            source_path=source_path,
            status=InvoiceStatus.EXTRACTED,
        )

    def _from_text(self, raw: str, source_path: str) -> Invoice:
        invoice_id = (
            self._find(r"Invoice\s*[#:]?\s*([A-Za-z0-9\-]+)", raw)
            or Path(source_path).stem
        )
        vendor = self._find(r"Vendor[:\s]+(.+)", raw) or self._find(r"From[:\s]+(.+)", raw) or "Unknown"
        amount = self._to_decimal(
            self._find(r"(?:Total|Amount Due|Balance)[:\s]+\$?([\d,]+\.?\d*)", raw) or "0"
        )

        items: List[LineItem] = []
        patterns = [
            r"([A-Za-z0-9_\-]+)\s+(\d+)\s*(?:@|x)?\s*\$?([\d.]+)?",
            r"Item[:\s]+([A-Za-z0-9_\-]+).*?Qty[:\s]+(\d+)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, raw, re.IGNORECASE):
                sku = m.group(1)
                qty = int(m.group(2))
                price = self._to_decimal(m.group(3)) if m.lastindex >= 3 else None
                items.append(LineItem(sku=sku, quantity=qty, unit_price=price))

        if not items:
            items = [LineItem(sku="UNKNOWN", quantity=1)]

        return Invoice(
            invoice_id=invoice_id.strip(),
            vendor=vendor.strip(),
            amount=amount,
            due_date=None,
            items=tuple(items),
            source_path=source_path,
            status=InvoiceStatus.EXTRACTED,
        )

    def _empty(self, source_path: str) -> Invoice:
        return Invoice(
            invoice_id=Path(source_path).stem,
            vendor="Unknown",
            amount=Decimal("0"),
            due_date=None,
            items=(LineItem(sku="UNKNOWN", quantity=1),),
            source_path=source_path,
            status=InvoiceStatus.EXTRACTED,
        )

    def _find(self, pattern: str, text: str) -> Optional[str]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else None

    def _to_decimal(self, value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value).replace(",", "").replace("$", "").strip())
        except (InvalidOperation, ValueError):
            return Decimal("0")
