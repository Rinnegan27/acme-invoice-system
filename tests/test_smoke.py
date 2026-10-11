"""Fast Aether Helix smoke gate: CLI invoice1 stub + case sim stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.sim.runner import run_case_simulation

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"


def test_core_package_absent() -> None:
    assert not (ROOT / "core").exists()


def test_invoice1_stub_pays(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "smoke_cli", use_grok=False)
    result = pipe.process_file(DATA / "invoice1.txt")
    assert result.status == "paid"
    assert result.invoice_id


def test_case_sim_stub_green(tmp_path: Path) -> None:
    report = run_case_simulation(tmp_path / "smoke_sim", use_grok=False)
    assert report.ok, [r.workflow_id for r in report.failed]
