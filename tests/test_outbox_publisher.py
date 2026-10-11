"""Outbox flush into JSONL event log."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_payment_flushes_outbox_to_jsonl(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "outbox", use_grok=False)
    result = pipe.process_file(DATA / "invoice_1001.txt")
    assert result.status == "paid"

    rows = pipe.saga.outbox_events()
    assert rows, "expected at least one outbox row"
    assert all(int(r["published"]) == 1 for r in rows)

    published = [
        e for e in pipe.events.read_all() if e.get("event_type") == "PaymentOutboxPublished"
    ]
    assert published, "expected PaymentOutboxPublished in JSONL"
    assert published[0]["payload"].get("source") == "outbox"
    assert published[0]["payload"].get("saga_event_type") == "PaymentSucceeded"
