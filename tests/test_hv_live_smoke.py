"""Live Grok smoke for an in-stock high-value invoice."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from invoice_automation.case_brief import is_live_xai_key
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.live_grok

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


@pytest.mark.skipif(
    not is_live_xai_key(os.getenv("XAI_API_KEY")),
    reason="XAI_API_KEY not configured",
)
def test_live_grok_hv_in_stock_smoke(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "hv_live", use_grok=True)
    result = pipe.process_file(DATA / "invoice_1160.txt")
    # Model may approve or reject after reflection; both are valid agent outcomes.
    assert result.status in {"paid", "rejected", "reconcile", "failed"}
    assert any(e.get("event_type") == "InvoiceExtracted" for e in result.events)
