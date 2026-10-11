"""End-to-end offline tests — Case Simulation Contract is the golden matrix."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.sim.runner import run_case_simulation

pytestmark = pytest.mark.black_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_case_simulation_is_green(tmp_path: Path) -> None:
    report = run_case_simulation(tmp_path / "sim", data_dir=DATA, use_grok=False)
    assert report.ok, [r.workflow_id for r in report.failed]


def test_process_directory_offline(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "runtime", use_grok=False)
    results = pipe.process_directory(DATA)
    assert len(results) >= 15
    statuses = {r.invoice_id: r.status for r in results}
    assert any(s == "paid" for s in statuses.values())
    assert any(s == "rejected" for s in statuses.values())


def test_high_value_reflection_path(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "runtime", use_grok=False)
    # In-stock HV fixture (1160); 1013 oversells WidgetA when lines are aggregated.
    result = pipe.process_file(DATA / "invoice_1160.txt")
    assert result.status == "paid"
    events = [e["event_type"] for e in result.events]
    assert "InvoiceExtracted" in events
    assert any(
        e.get("event_type") == "InvoiceApproved" and e.get("payload", {}).get("reflected")
        for e in result.events
    )
