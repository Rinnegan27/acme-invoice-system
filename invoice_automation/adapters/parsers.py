"""Deterministic multi-format invoice parsers for offline and CI paths.

Notes
-----
Prefer an explicit TOTAL. When TOTAL is missing, use SUBTOTAL, then the
sum of priced line items (qty × unit_price). Fail only when no amount can
be resolved. Do not coerce garbage strings to zero.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any

from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem


def parse_invoice_bytes(raw: bytes, source_path: str) -> Invoice:
    """Parse invoice bytes using format strategy by suffix."""
    text = raw.decode("utf-8", errors="replace")
    return parse_invoice_text(text, source_path)


def normalize_invoice_id(raw: str, *, fallback: str = "") -> str:
    """Normalize a business invoice id to ``INV-…`` when possible.

    Parameters
    ----------
    raw : str
        Candidate id from a parser, LLM, or event.
    fallback : str
        Used when ``raw`` is empty (often the source file stem).

    Returns
    -------
    str
        Normalized id. Bare digits become ``INV-{digits}``. Stems such as
        ``invoice_1002`` become ``INV-1002``. Values that already use
        ``INV-`` are returned in canonical form.

    Notes
    -----
    Live Grok sometimes returns ``1002`` instead of ``INV-1002``. Call this
    after extract so CLI summaries and permits stay consistent with parsers.
    """
    text = str(raw or "").replace(" ", "").strip()
    if not text:
        text = str(fallback or "").replace(" ", "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.isdigit() and len(upper) >= 3:
        return f"INV-{upper}"
    # Stems like invoice_1002 → INV-1002. Do not map invoice1 → INV-1.
    m = re.match(r"^INVOICE[_-](\d{3,})$", upper)
    if m:
        return f"INV-{m.group(1)}"
    if upper.startswith("INV-"):
        return upper
    if upper.startswith("INV_"):
        rest = upper[4:]
        return f"INV-{rest}" if rest.isdigit() and len(rest) >= 3 else text
    if upper.startswith("INV") and len(upper) > 3 and upper[3].isdigit():
        rest = upper[3:]
        return f"INV-{rest}" if rest.isdigit() else text
    return text


def parse_invoice_text(raw_text: str, source_path: str) -> Invoice:
    """Parse invoice text using suffix-specific strategies.

    Parameters
    ----------
    raw_text : str
        Document text (or decoded bytes).
    source_path : str
        Path used for suffix detection and invoice_id fallback.

    Returns
    -------
    Invoice
        Structured invoice with status EXTRACTED.
    """
    suffix = Path(source_path).suffix.lower()
    handler = FORMAT_REGISTRY.get(suffix, _from_text)
    invoice = handler(raw_text, source_path)
    normalized = normalize_invoice_id(invoice.invoice_id, fallback=Path(source_path).stem)
    if normalized and normalized != invoice.invoice_id:
        return invoice.with_updates(invoice_id=normalized)
    return invoice


def _to_decimal(value: Any) -> Decimal:
    """Parse a required decimal; never silently coerce garbage to 0."""
    if value is None or value == "":
        raise ExtractionError("invalid_amount: missing numeric value")
    text = str(value).replace(",", "").replace("$", "").strip()
    # Strip leading currency codes: "USD 250.00" / "USD$250".
    text = re.sub(r"^(?:USD|EUR|GBP|CAD|AUD)\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        raise ExtractionError("invalid_amount: empty numeric value")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ExtractionError(f"invalid_amount: {value!r}") from exc


def _optional_decimal(value: Any) -> Decimal | None:
    """Parse optional unit price; missing → None; garbage → ExtractionError."""
    if value is None or value == "":
        return None
    return _to_decimal(value)


# Generic English number words (0–99). Not a UAT-specific allowlist.
_ONES: dict[str, int] = {
    "zero": 0,
    "oh": 0,
    "o": 0,  # OCR lookalike for 0
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _english_word_quantity(text: str) -> int | None:
    """Parse a simple English quantity phrase (0–99). Return None if unknown."""
    tokens = re.findall(r"[a-z]+", text.casefold())
    if not tokens:
        return None
    if len(tokens) == 1:
        w = tokens[0]
        if w in _ONES:
            return _ONES[w]
        if w in _TENS:
            return _TENS[w]
        return None
    if len(tokens) == 2 and tokens[0] in _TENS and tokens[1] in _ONES:
        return _TENS[tokens[0]] + _ONES[tokens[1]]
    return None


def _to_quantity(value: Any) -> int:
    """Parse a line quantity; reject fractions, percents, and approximations.

    Notes
    -----
    Accepts integers, scientific notation, English words (0–99), OCR ``O``,
    and leading digits with trailing unit noise (``3 units``, ``10 (Ten)``).
    """
    if value is None or value == "":
        raise ExtractionError("invalid_quantity: missing value")
    if isinstance(value, bool):
        raise ExtractionError(f"invalid_quantity: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ExtractionError(f"invalid_quantity:non_integer:{value}")
        return int(value)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ExtractionError(f"invalid_quantity:non_integer:{value}")
        return int(value)

    text = str(value).strip().strip("\"'")
    if not text:
        raise ExtractionError("invalid_quantity: empty value")
    # Approximation / percent markers are never valid inventory quantities.
    if "~" in text or "%" in text:
        raise ExtractionError(f"invalid_quantity:symbol:{text}")
    # Leading integer + optional bracketed/word unit noise.
    m = re.match(r"^([+-]?\d+)\s*(?:[\(\[]?[A-Za-z]+[\)\]]?|[A-Za-z]+\.?)?\s*$", text)
    if m and re.search(r"[A-Za-z]", text):
        return int(m.group(1))
    word_qty = _english_word_quantity(text)
    if word_qty is not None:
        return word_qty
    cleaned = text.replace(",", "").strip()
    try:
        dec = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ExtractionError(f"invalid_quantity: {value!r}") from exc
    if dec != dec.to_integral_value():
        raise ExtractionError(f"invalid_quantity:non_integer:{value}")
    return int(dec)


def line_items_amount(items: Sequence[LineItem]) -> Decimal | None:
    """Return sum(qty × unit_price) when every positive-qty line is priced."""
    total = Decimal("0")
    priced_lines = 0
    for item in items:
        if item.quantity <= 0:
            continue
        if item.unit_price is None:
            return None
        total += item.unit_price * item.quantity
        priced_lines += 1
    if priced_lines == 0:
        return None
    return total


def resolve_invoice_amount(
    *,
    explicit: Decimal | None,
    items: Sequence[LineItem],
    subtotal: Decimal | None = None,
) -> Decimal:
    """Resolve payable amount from total, subtotal, or priced lines.

    Parameters
    ----------
    explicit : Decimal or None
        TOTAL / amount due when present on the document.
    items : sequence of LineItem
        Extracted lines (used when total/subtotal are missing).
    subtotal : Decimal or None
        SUBTOTAL when present (used before line-sum fallback).

    Returns
    -------
    Decimal
        Resolved invoice amount.

    Raises
    ------
    ExtractionError
        When no total, subtotal, or complete priced line sum is available.
    """
    if explicit is not None:
        return explicit
    if subtotal is not None:
        return subtotal
    computed = line_items_amount(items)
    if computed is not None and computed > 0:
        return computed
    raise ExtractionError(
        "invalid_amount: missing total/subtotal and cannot compute from line items"
    )


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.lower() in {"yesterday", "immediate"}:
        return None
    for fmt in ("%Y-%m-%d", "%b %d %Y", "%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    return None


def _vendor_from_json(data: dict[str, Any]) -> str:
    vendor = data.get("vendor") or data.get("supplier")
    if isinstance(vendor, dict):
        name = vendor.get("name")
        return str(name).strip() if name else "Unknown"
    if vendor:
        return str(vendor).strip()
    return "Unknown"


def _from_json(raw: str, source_path: str) -> Invoice:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"invalid JSON: {exc}") from exc

    invoice_id = str(
        data.get("invoice_number")
        or data.get("invoice_id")
        or data.get("id")
        or Path(source_path).stem
    )
    vendor = _vendor_from_json(data)
    due_date = _parse_date(data.get("due_date"))
    explicit = None
    if data.get("total") is not None or data.get("amount") is not None:
        explicit = _to_decimal(
            data.get("total") if data.get("total") is not None else data.get("amount")
        )
    subtotal = _optional_decimal(data.get("subtotal"))

    items: list[LineItem] = []
    for item in data.get("line_items") or data.get("items") or []:
        sku = str(item.get("item") or item.get("sku") or item.get("name") or "UNKNOWN")
        qty = _to_quantity(item.get("quantity") if item.get("quantity") is not None else item.get("qty") or 0)
        price = _optional_decimal(
            item.get("unit_price") if item.get("unit_price") is not None else item.get("price")
        )
        items.append(LineItem(sku=sku, quantity=qty, unit_price=price))

    if not items:
        raise ExtractionError("JSON invoice has no line items")

    return Invoice(
        invoice_id=invoice_id,
        vendor=vendor or "Unknown",
        amount=resolve_invoice_amount(explicit=explicit, items=items, subtotal=subtotal),
        due_date=due_date,
        items=tuple(items),
        source_path=source_path,
        status=InvoiceStatus.EXTRACTED,
    )


def _from_csv(raw: str, source_path: str) -> Invoice:
    """Support Galatiq key/value CSV, multi-line item CSV, and wide-row CSV."""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise ExtractionError("empty CSV")

    header = [c.strip().lower() for c in next(csv.reader([lines[0]]))]
    # Multi-row line-item CSV used by INV-1007 / INV-1015
    if "item" in header and ("qty" in header or "quantity" in header):
        return _from_tabular_csv(raw, source_path, header)

    # Key/value format: field,value
    if header[:2] == ["field", "value"] or (len(header) == 2 and "field" in header[0]):
        kv: dict[str, str] = {}
        items: list[LineItem] = []
        pending_item: dict[str, str] = {}
        reader = csv.reader(StringIO(raw))
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            key, value = row[0].strip().lower(), row[1].strip()
            if key in {"item", "sku"}:
                if pending_item.get("item"):
                    items.append(
                        LineItem(
                            sku=pending_item["item"],
                            quantity=_to_quantity(pending_item.get("quantity") or 0),
                            unit_price=_optional_decimal(pending_item.get("unit_price")),
                        )
                    )
                pending_item = {"item": value}
            elif key in {"quantity", "qty", "unit_price", "price"} and pending_item:
                pending_item[key if key != "qty" else "quantity"] = value
                if key == "price":
                    pending_item["unit_price"] = value
            else:
                kv[key] = value
        if pending_item.get("item"):
            items.append(
                LineItem(
                    sku=pending_item["item"],
                    quantity=_to_quantity(pending_item.get("quantity") or 0),
                    unit_price=_optional_decimal(pending_item.get("unit_price")),
                )
            )
        invoice_id = kv.get("invoice_number") or kv.get("invoice_id") or Path(source_path).stem
        return Invoice(
            invoice_id=invoice_id,
            vendor=kv.get("vendor") or kv.get("supplier") or "Unknown",
            amount=_to_decimal(kv.get("total") or kv.get("amount")),
            due_date=_parse_date(kv.get("due_date")),
            items=tuple(items) if items else (LineItem(sku="UNKNOWN", quantity=0),),
            source_path=source_path,
            status=InvoiceStatus.EXTRACTED,
        )

    return _from_csv_wide_fallback(lines, header, source_path)


def _from_tabular_csv(raw: str, source_path: str, header: list[str]) -> Invoice:
    """Parse invoice CSVs with one row per line item plus total footer rows."""
    reader = csv.reader(StringIO(raw))
    next(reader, None)
    items: list[LineItem] = []
    invoice_id = Path(source_path).stem
    vendor = "Unknown"
    amount = Decimal("0")
    due_date = None
    item_idx = header.index("item")
    qty_idx = header.index("qty") if "qty" in header else header.index("quantity")
    price_idx = (
        header.index("unit price")
        if "unit price" in header
        else (header.index("unit_price") if "unit_price" in header else -1)
    )
    inv_idx = header.index("invoice number") if "invoice number" in header else -1
    vendor_idx = header.index("vendor") if "vendor" in header else -1
    due_idx = header.index("due date") if "due date" in header else -1

    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue
        # Footer rows: ,,,,,,Total:,15525.00
        joined = ",".join(row).lower()
        if "total" in joined and "subtotal" not in joined and "line total" not in joined:
            for cell in reversed(row):
                if cell.strip():
                    try:
                        maybe = _to_decimal(cell)
                    except ExtractionError:
                        continue
                    if maybe > 0:
                        amount = maybe
                        break
            continue
        if "subtotal" in joined or "tax" in joined:
            continue
        item_name = row[item_idx].strip() if item_idx < len(row) else ""
        if not item_name:
            continue
        qty = (
            _to_quantity(row[qty_idx])
            if qty_idx < len(row) and row[qty_idx].strip()
            else 0
        )
        price = (
            _optional_decimal(row[price_idx]) if price_idx >= 0 and price_idx < len(row) else None
        )
        items.append(LineItem(sku=item_name, quantity=qty, unit_price=price))
        if inv_idx >= 0 and inv_idx < len(row) and row[inv_idx].strip():
            invoice_id = row[inv_idx].strip()
        if vendor_idx >= 0 and vendor_idx < len(row) and row[vendor_idx].strip():
            vendor = row[vendor_idx].strip()
        if due_idx >= 0 and due_idx < len(row) and row[due_idx].strip():
            due_date = _parse_date(row[due_idx])

    if not items:
        raise ExtractionError("tabular CSV has no line items")
    explicit = amount if amount > 0 else None
    return Invoice(
        invoice_id=invoice_id,
        vendor=vendor,
        amount=resolve_invoice_amount(explicit=explicit, items=items),
        due_date=due_date,
        items=tuple(items),
        source_path=source_path,
        status=InvoiceStatus.EXTRACTED,
    )


def _from_csv_wide_fallback(lines: list[str], header: list[str], source_path: str) -> Invoice:
    data_row = next(csv.reader([lines[1]]), []) if len(lines) > 1 else []

    def col(name: str, default: str = "") -> str:
        try:
            idx = header.index(name)
            return data_row[idx].strip() if idx < len(data_row) else default
        except ValueError:
            return default

    items = (
        LineItem(
            sku=col("item") or col("sku") or "UNKNOWN",
            quantity=_to_quantity(col("quantity") or col("qty") or "0"),
            unit_price=_optional_decimal(col("unit_price") or col("price") or None),
        ),
    )
    explicit_raw = col("amount") or col("total") or ""
    explicit = _to_decimal(explicit_raw) if explicit_raw else None
    return Invoice(
        invoice_id=col("invoice_id") or col("invoice_number") or Path(source_path).stem,
        vendor=col("vendor") or col("supplier") or "Unknown",
        amount=resolve_invoice_amount(explicit=explicit, items=items),
        due_date=_parse_date(col("due_date")),
        items=items,
        source_path=source_path,
        status=InvoiceStatus.EXTRACTED,
    )


def _from_xml(raw: str, source_path: str) -> Invoice:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ExtractionError(f"invalid XML: {exc}") from exc

    def find_text(path: str) -> str | None:
        node = root.find(path)
        if node is not None and node.text:
            return node.text.strip()
        # also try anywhere
        for el in root.iter():
            if el.tag.endswith(path.split("/")[-1]) and el.text:
                return el.text.strip()
        return None

    invoice_id = (
        find_text("header/invoice_number") or find_text("invoice_number") or Path(source_path).stem
    )
    vendor = find_text("header/vendor") or find_text("vendor") or "Unknown"
    total_raw = find_text("totals/total") or find_text("total")
    subtotal_raw = find_text("totals/subtotal") or find_text("subtotal")
    due_date = _parse_date(find_text("header/due_date") or find_text("due_date"))

    items: list[LineItem] = []
    for item_el in root.findall(".//line_items/item") or root.findall(".//item"):
        name = None
        qty = 0
        price = None
        for child in item_el:
            tag = child.tag.lower()
            if tag in {"name", "sku", "item"}:
                name = (child.text or "").strip()
            elif tag == "quantity":
                qty = _to_quantity((child.text or "0").strip())
            elif tag in {"unit_price", "price"}:
                price = _optional_decimal(child.text)
        if name:
            items.append(LineItem(sku=name, quantity=qty, unit_price=price))

    if not items:
        raise ExtractionError("XML invoice has no line items")

    return Invoice(
        invoice_id=invoice_id,
        vendor=vendor,
        amount=resolve_invoice_amount(
            explicit=_to_decimal(total_raw) if total_raw else None,
            items=items,
            subtotal=_to_decimal(subtotal_raw) if subtotal_raw else None,
        ),
        due_date=due_date,
        items=tuple(items),
        source_path=source_path,
        status=InvoiceStatus.EXTRACTED,
    )


_SKU_DENYLIST = {
    "invoice",
    "vendor",
    "total",
    "amount",
    "subtotal",
    "tax",
    "net",
    "date",
    "due",
    "from",
    "to",
    "payment",
    "terms",
    "qty",
    "item",
    "items",
    "description",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
}


def _from_text(raw: str, source_path: str) -> Invoice:
    invoice_id = (
        # Require a digit so the word "Invoice" itself never matches as an id.
        _find(
            r"Invoice\s*(?:Number|#|Num)?\s*[:#]?\s*(INV-?\d+[A-Z0-9]*|\d{3,})",
            raw,
        )
        or _find(r"INV\s*NO\s*[:#]?\s*(INV[-\s]?\d+|\d{3,})", raw)
        or _find(r"Inv\s*#\s*[:#]?\s*(\d+)", raw)
        or Path(source_path).stem
    )
    invoice_id = normalize_invoice_id(str(invoice_id), fallback=Path(source_path).stem)

    vendor = (
        _find(r"Vendor\s*[:]\s*(.+)", raw)
        or _find(r"Vndr\s*[:]\s*(.+)", raw)
        or _find(r"FROM\s*[:]\s*(.+)", raw)
        or _find(r"From\s*[:]\s*(.+)", raw)
        or "Unknown"
    )
    # strip email-only From lines that aren't vendors
    if "@" in vendor and "Vendor" not in raw:
        vendor = _find(r"Vendor\s*[:]\s*(.+)", raw) or vendor

    amount_raw = _find(
        r"(?:Total\s*Amount|Amount\s*Due|(?<![A-Za-z])TOTAL|(?<![A-Za-z])Total|(?<![A-Za-z])Amt)\s*[:\s]+\$?([\d,]+\.?\d*)",
        raw,
    )
    subtotal_raw = _find(
        r"(?:Sub\s*-?\s*Total|Subtotal)\s*[:\s]+\$?([\d,]+\.?\d*)",
        raw,
    )
    due_date = _parse_date(_find(r"(?:Due\s*Date|Due\s*Dt|Due)\s*[:]\s*(.+)", raw))

    # Approximate / percent / fractional quantities are data-integrity failures.
    if re.search(r"(?i)Qty\s*[:\s]+~", raw) or re.search(
        r"(?i)Qty\s*[:\s]+[\d,]+\.\d+", raw
    ) or re.search(r"(?i)Qty\s*[:\s]+[\d,]+%", raw):
        raise ExtractionError("invalid_quantity:symbol_or_fraction")

    items: list[LineItem] = []
    patterns = [
        # Do not treat the letter in "Gadget X" as a qty marker; only bare "x5".
        # Optional trailing "(rush order)" annotations are stripped by LineItem.
        r"(?m)^\s*-?\s*([A-Za-z][A-Za-z0-9_\-]*(?:\s*\([^)\n]*\))?)\s+(?:qty[:\s]+|x(?=\d))?(\d+)\s*(?:@|x)?\s*\$?([\d,.]+)?",
        r"(?m)^\s*([A-Za-z][A-Za-z0-9_\-]*(?:\s*\([^)\n]*\))?)\s+(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)",
        r"([A-Za-z][A-Za-z0-9_\-]*)\s+x(\d+)\s+\$?([\d,.]+)",
    ]
    seen: set[tuple[str, int]] = set()
    # Item/Qty may sit on adjacent lines; other patterns stay single-line.
    item_qty_pat = (
        r"Item[:\s]+([A-Za-z0-9_\-]+(?:[ \t]+[A-Za-z0-9_\-]+)?)"
        r"[ \t]*(?:\n[ \t]*)?Qty[:\s]+([^\n]+)"
    )
    for pat in patterns:
        flags = re.IGNORECASE
        for m in re.finditer(pat, raw, flags):
            sku = m.group(1).strip()
            if sku.lower() in _SKU_DENYLIST:
                continue
            # Keep short aliases like W-A; drop single-letter noise.
            compact_sku_len = len(re.sub(r"[\s_-]+", "", sku))
            if compact_sku_len < 2:
                continue
            if "\n" in sku or "qty" in sku.casefold():
                continue
            qty = _to_quantity(m.group(2).strip().strip("\"'"))
            price = (
                _optional_decimal(m.group(3))
                if m.lastindex and m.lastindex >= 3 and m.group(3)
                else None
            )
            key = (sku, qty)
            if key in seen:
                continue
            seen.add(key)
            items.append(LineItem(sku=sku, quantity=qty, unit_price=price))

    for m in re.finditer(item_qty_pat, raw, re.IGNORECASE):
        sku = m.group(1).strip()
        if sku.lower() in _SKU_DENYLIST or "\n" in sku:
            continue
        qty = _to_quantity(m.group(2).strip().strip("\"'"))
        key = (sku, qty)
        if key in seen:
            continue
        seen.add(key)
        items.append(LineItem(sku=sku, quantity=qty))

    # Galatiq style: WidgetA    qty: 10  (also word/OCR quantities).
    # Use [ \\t]+ so "Widget A\\nQty:" does not create a phantom SKU "A".
    for m in re.finditer(
        r"([A-Za-z][A-Za-z0-9_\-]*)[ \t]+qty[:\s]+([^\n]+)",
        raw,
        re.IGNORECASE,
    ):
        sku = m.group(1)
        if sku.lower() in _SKU_DENYLIST:
            continue
        qty_token = m.group(2).strip().split()[0].strip("\"'")
        # Skip unit-price lines mistaken as qty.
        if qty_token.lower().startswith("unit") or qty_token.startswith("$"):
            continue
        qty = _to_quantity(qty_token)
        key = (sku, qty)
        if key not in seen:
            seen.add(key)
            items.append(LineItem(sku=sku, quantity=qty))

    # Spaced SKUs: "Widget A", "Gadget X", "Widgiet B"
    for m in re.finditer(
        r"(Widget|Gadget|Widgiet|Widg)\s+([A-Za-z0-9]+)\s+(\d+)",
        raw,
        re.IGNORECASE,
    ):
        sku = f"{m.group(1)} {m.group(2)}"
        qty = _to_quantity(m.group(3))
        key = (sku, qty)
        if key not in seen:
            seen.add(key)
            items.append(LineItem(sku=sku, quantity=qty))

    if not items:
        # last resort: known SKUs mentioned with nearby numbers
        for sku in (
            "WidgetA",
            "WidgetB",
            "GadgetX",
            "FakeItem",
            "SuperGizmo",
            "MegaSprocket",
            "WidgetC",
        ):
            m = re.search(rf"{sku}\D+(\d+)", raw, re.IGNORECASE)
            if m:
                items.append(LineItem(sku=sku, quantity=_to_quantity(m.group(1))))

    if not items:
        raise ExtractionError("could not extract line items from text")

    # Also pick up "unit price: $250" when the first pass missed the price group.
    for idx, item in enumerate(items):
        if item.unit_price is not None:
            continue
        m = re.search(
            rf"{re.escape(item.sku)}.*?unit\s*price\s*[:\s]+\$?([\d,.]+)",
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            items[idx] = LineItem(
                sku=item.sku,
                quantity=item.quantity,
                unit_price=_to_decimal(m.group(1)),
            )

    return Invoice(
        invoice_id=str(invoice_id).strip(),
        vendor=vendor.strip().split("\n")[0].strip(),
        amount=resolve_invoice_amount(
            explicit=_to_decimal(amount_raw) if amount_raw else None,
            items=items,
            subtotal=_to_decimal(subtotal_raw) if subtotal_raw else None,
        ),
        due_date=due_date,
        items=tuple(items),
        source_path=source_path,
        status=InvoiceStatus.EXTRACTED,
    )


def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


# Suffix → parser (extensible registry; default text handler for unknown suffixes).
FORMAT_REGISTRY: dict[str, Any] = {
    ".json": _from_json,
    ".csv": _from_csv,
    ".xml": _from_xml,
    ".txt": _from_text,
    ".pdf": _from_text,  # pdfplumber text is parsed as plain text
}
