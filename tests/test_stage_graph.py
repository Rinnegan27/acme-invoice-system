"""Strict validation for the explicit orchestration stage graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.domain.models import StageName
from invoice_automation.orchestration.pipeline import Pipeline
from invoice_automation.orchestration.stage_graph import (
    EDGES,
    STAGE_ORDER,
    TERMINAL_PAID,
    TERMINAL_RECONCILE,
    TERMINAL_REJECT,
    edge_map,
    select_ready_stage,
    validate_graph,
)

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_validate_graph_is_complete() -> None:
    validate_graph()
    by_src = edge_map()
    assert StageName.INGESTION.value in by_src
    assert any(e.target == TERMINAL_REJECT for e in EDGES)
    assert any(e.target == TERMINAL_PAID for e in EDGES)
    assert any(e.target == TERMINAL_RECONCILE for e in EDGES)


def test_select_ready_prefers_upstream_wavefront() -> None:
    depths = {
        StageName.INGESTION: 0,
        StageName.VALIDATION: 2,
        StageName.APPROVAL: 5,
        StageName.PAYMENT: 1,
    }
    chosen = select_ready_stage(lambda s: depths[s], STAGE_ORDER)
    assert chosen == StageName.VALIDATION


def test_select_ready_none_when_idle() -> None:
    assert select_ready_stage(lambda _s: 0, STAGE_ORDER) is None


def test_select_ready_respects_allowed_subset() -> None:
    depths = {
        StageName.INGESTION: 1,
        StageName.VALIDATION: 1,
        StageName.APPROVAL: 0,
        StageName.PAYMENT: 0,
    }
    chosen = select_ready_stage(
        lambda s: depths[s],
        {StageName.VALIDATION, StageName.APPROVAL},
    )
    assert chosen == StageName.VALIDATION


def test_drain_follows_wavefront_and_records_transitions(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "g", use_grok=False, profile="case")
    result = pipe.process_file(DATA / "invoice_1001.txt")
    assert result.status == "paid"
    state = pipe.last_drain_state
    assert state is not None
    assert state.steps >= 4
    assert state.transitions is not None
    # Wavefront order: ingestion before validation before approval before payment.
    runs = [t.removeprefix("run:") for t in state.transitions if t.startswith("run:")]
    assert runs[0] == "ingestion"
    assert "validation" in runs
    assert "approval" in runs
    assert "payment" in runs
    assert runs.index("ingestion") < runs.index("validation")
    assert runs.index("validation") < runs.index("approval")
    assert runs.index("approval") < runs.index("payment")


def test_drain_rejects_without_payment_stage(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "r", use_grok=False, profile="case")
    result = pipe.process_file(DATA / "invoice_1002.txt")
    assert result.status == "rejected"
    assert any(i.startswith("insufficient_stock") for i in result.issues)
    state = pipe.last_drain_state
    assert state is not None
    runs = [t for t in (state.transitions or []) if t.startswith("run:")]
    assert "run:payment" not in runs
