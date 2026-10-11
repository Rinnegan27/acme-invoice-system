"""Local OTLP/JSON span batch file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_otlp_traces_file_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod")
    work = tmp_path / "run"
    pipe = Pipeline(work_dir=work, use_grok=False)
    pipe.process_file(DATA / "invoice_1001.txt")
    otlp = work / "otlp_traces.json"
    assert otlp.is_file()
    batch = json.loads(otlp.read_text(encoding="utf-8"))
    spans = batch["resourceSpans"][0]["scopeSpans"][0]["spans"]
    names = {s["name"] for s in spans}
    assert "stage.ingestion" in names
    assert "stage.payment" in names
