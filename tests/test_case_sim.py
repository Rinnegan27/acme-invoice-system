"""Case Simulation Contract — shared runner golden harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.sim.runner import SimReport, run_case_simulation

pytestmark = pytest.mark.black_box


def test_case_simulation_contract_offline(tmp_path: Path) -> None:
    report = run_case_simulation(tmp_path / "sim", use_grok=False)
    assert report.total >= 20
    failures = [f"{r.workflow_id}: {r.message or r.actual}" for r in report.failed]
    assert report.ok, "Case sim failures:\n" + "\n".join(failures)


def test_case_simulation_report_serializes(tmp_path: Path) -> None:
    report = run_case_simulation(tmp_path / "sim2", use_grok=False)
    out = tmp_path / "last_report.json"
    report.save(out)
    loaded = SimReport.load(out)
    assert loaded is not None
    assert loaded.passed == report.passed
    assert loaded.total == report.total
