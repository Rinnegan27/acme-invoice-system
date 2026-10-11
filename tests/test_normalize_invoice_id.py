"""Business invoice id normalization (parsers + live Grok bare digits)."""

from __future__ import annotations

import pytest

from invoice_automation.adapters.parsers import normalize_invoice_id
from invoice_automation.orchestration.pipeline import _business_invoice_id

pytestmark = pytest.mark.white_box


@pytest.mark.parametrize(
    ("raw", "fallback", "expected"),
    [
        ("1002", "", "INV-1002"),
        ("INV-1002", "", "INV-1002"),
        ("INV1002", "", "INV-1002"),
        ("INV_1002", "", "INV-1002"),
        ("invoice_1002", "", "INV-1002"),
        ("", "invoice_1002", "INV-1002"),
        ("invoice1", "", "invoice1"),
        ("invoice_1004_revised", "", "invoice_1004_revised"),
    ],
)
def test_normalize_invoice_id(raw: str, fallback: str, expected: str) -> None:
    assert normalize_invoice_id(raw, fallback=fallback) == expected


def test_business_invoice_id_normalizes_bare_digits() -> None:
    events = [
        {"event_type": "InvoiceReceived", "invoice_id": "invoice_1002", "payload": {}},
        {
            "event_type": "InvoiceExtracted",
            "invoice_id": "1002",
            "payload": {"invoice": {"invoice_id": "1002"}},
        },
    ]
    assert _business_invoice_id(events, fallback="invoice_1002") == "INV-1002"


def test_business_invoice_id_alias_stem_does_not_beat_extract() -> None:
    events = [
        {"event_type": "InvoiceReceived", "invoice_id": "invoice1", "payload": {}},
        {
            "event_type": "InvoiceExtracted",
            "invoice_id": "INV-1001",
            "payload": {"invoice": {"invoice_id": "INV-1001"}},
        },
    ]
    assert _business_invoice_id(events, fallback="invoice1") == "INV-1001"
