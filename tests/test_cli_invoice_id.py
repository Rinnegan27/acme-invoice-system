"""CLI and pipeline results prefer business INV- ids."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.smoke

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_invoice1_alias_reports_business_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod")
    pipe = Pipeline(work_dir=tmp_path / "run", use_grok=False)
    result = pipe.process_file(DATA / "invoice1.txt")
    assert result.status == "paid"
    assert str(result.invoice_id).upper().startswith("INV-")


def test_rejected_file_stem_not_confused_with_inv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod")
    pipe = Pipeline(work_dir=tmp_path / "run2", use_grok=False)
    result = pipe.process_file(DATA / "invoice_1002.txt")
    assert result.status == "rejected"
    assert result.invoice_id == "INV-1002"
