"""Staged human-in-the-loop review desk flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.black_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_extract_and_validate_clean(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False)
    draft = pipe.extract_and_validate(DATA / "invoice_1001.txt")
    assert draft.invoice.invoice_id == "INV-1001"
    assert draft.issues == ()
    assert draft.review_status == "CLEAR"
    assert "WidgetA" in draft.raw_text
    assert not draft.hard_blocked


def test_human_approve_clean_pays(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False)
    draft = pipe.extract_and_validate(DATA / "invoice_1001.txt")
    result = pipe.human_approve(draft)
    assert result.status == "paid"
    assert any(e["event_type"] == "PaymentSucceeded" for e in result.events)


def test_human_approve_blocked_unknown_sku(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False)
    draft = pipe.extract_and_validate(DATA / "invoice_1008.txt")
    assert draft.hard_blocked
    assert draft.review_status == "BLOCKED"
    with pytest.raises(ValidationError):
        pipe.human_approve(draft)


def test_auto_approve_clean_pays(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False)
    draft = pipe.extract_and_validate(DATA / "invoice_1001.txt")
    result = pipe.auto_approve(draft)
    assert result.status == "paid"


def test_human_reject(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False)
    draft = pipe.extract_and_validate(DATA / "invoice_1001.txt")
    result = pipe.human_reject(draft, reason="Hold for vendor call")
    assert result.status == "rejected"
    assert "Hold for vendor call" in result.approval_reason
