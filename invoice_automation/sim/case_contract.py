"""Case Simulation Contract (CSC). Galatiq case workflows W1–W10."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal[
    "auto_complete",
    "analyst_pay_denied",
    "vp_pay",
    "vp_never_pay_blocked",
    "extract_ok",
    "idempotent_reingest",
    "reject_path",
    "role_gate",
    "fault_injection",
]


@dataclass(frozen=True)
class CaseSpec:
    """One workflow check that the sim can run."""

    workflow_id: str
    title: str
    files: tuple[str, ...]
    mode: Mode
    expect_status: str | None = None
    expect_issue_substr: str | None = None
    forbid_paid: bool = False
    notes: str = ""


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        workflow_id="W1a",
        title="STP clean TXT",
        files=("invoice_1001.txt",),
        mode="auto_complete",
        expect_status="paid",
        notes="Normal order within stock",
    ),
    CaseSpec(
        workflow_id="W1b",
        title="STP clean JSON",
        files=("invoice_1004.json",),
        mode="auto_complete",
        expect_status="paid",
    ),
    CaseSpec(
        workflow_id="W1c",
        title="STP clean CSV",
        files=("invoice_1006.csv",),
        mode="auto_complete",
        expect_status="paid",
    ),
    CaseSpec(
        workflow_id="W1d",
        title="STP clean TXT 1010",
        files=("invoice_1010.txt",),
        mode="auto_complete",
        expect_status="paid",
    ),
    CaseSpec(
        workflow_id="W1e",
        title="STP clean XML",
        files=("invoice_1014.xml",),
        mode="auto_complete",
        expect_status="paid",
    ),
    CaseSpec(
        workflow_id="W1f",
        title="STP clean CSV 1015",
        files=("invoice_1015.csv",),
        mode="auto_complete",
        expect_status="paid",
    ),
    CaseSpec(
        workflow_id="W2a",
        title="Stock mismatch 1002",
        files=("invoice_1002.txt",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="insufficient_stock",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W2b",
        title="Stock mismatch 1007",
        files=("invoice_1007.csv",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="insufficient_stock",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W3",
        title="Fraud / zero-stock FakeItem",
        files=("invoice_1003.txt",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="zero_stock",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W4a",
        title="Unknown SKU 1008",
        files=("invoice_1008.txt",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="unknown_item",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W4b",
        title="Unknown SKU 1016",
        files=("invoice_1016.json",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="unknown_item",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W5",
        title="Invalid quantity / negative",
        files=("invoice_1009.json",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="invalid_quantity",
        forbid_paid=True,
        notes="Also covers negative_amount integrity",
    ),
    CaseSpec(
        workflow_id="W6a",
        title="High-value analyst pay denied",
        files=("invoice_1160.txt",),
        mode="analyst_pay_denied",
        forbid_paid=True,
        notes="Analyst cannot pay >$10k (in-stock HV fixture)",
    ),
    CaseSpec(
        workflow_id="W6a2",
        title="High-value clean VP pay",
        files=("invoice_1160.txt",),
        mode="vp_pay",
        expect_status="paid",
        notes="In-stock HV; stub VP reflection approves",
    ),
    CaseSpec(
        workflow_id="W6b",
        title="High-value multi-line stock aggregate reject",
        files=("invoice_1013.json",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="insufficient_stock",
        forbid_paid=True,
        notes="WidgetA lines sum above seed stock when aggregated by SKU",
    ),
    CaseSpec(
        workflow_id="W6c",
        title="High-value with issues never VP-paid without override",
        files=("invoice_1002.txt",),
        mode="vp_never_pay_blocked",
        forbid_paid=True,
        expect_issue_substr="insufficient_stock",
    ),
    CaseSpec(
        workflow_id="W7a",
        title="Extract TXT",
        files=("invoice_1001.txt",),
        mode="extract_ok",
    ),
    CaseSpec(
        workflow_id="W7b",
        title="Extract JSON",
        files=("invoice_1005.json",),
        mode="extract_ok",
    ),
    CaseSpec(
        workflow_id="W7c",
        title="Extract CSV",
        files=("invoice_1006.csv",),
        mode="extract_ok",
    ),
    CaseSpec(
        workflow_id="W7d",
        title="Extract XML",
        files=("invoice_1014.xml",),
        mode="extract_ok",
    ),
    CaseSpec(
        workflow_id="W7e",
        title="Extract PDF twin as TXT preferred",
        files=("invoice_1011.txt",),
        mode="extract_ok",
    ),
    CaseSpec(
        workflow_id="W8",
        title="Idempotent re-ingest",
        files=(),
        mode="idempotent_reingest",
        notes="sample_paths ×2 → stable unique source rows",
    ),
    CaseSpec(
        workflow_id="W9",
        title="Human reject path",
        files=("invoice_1001.txt",),
        mode="reject_path",
        expect_status="rejected",
        forbid_paid=True,
    ),
    CaseSpec(
        workflow_id="W10",
        title="Escalate + VP queue gate",
        files=("invoice_1001.txt",),
        mode="role_gate",
        notes="Escalate moves to VP queue; bulk policy skips findings",
    ),
    CaseSpec(
        workflow_id="F1",
        title="Fault: prompt-injection vendor never pays",
        files=(),
        mode="fault_injection",
        expect_status="blocked",
        forbid_paid=True,
        notes="synthetic invoice with injection markers",
    ),
    CaseSpec(
        workflow_id="F2",
        title="Fault: naked payment queue without permit",
        files=("invoice_1001.txt",),
        mode="fault_injection",
        expect_status="no_pay",
        forbid_paid=True,
        notes="PaymentWorker must refuse missing PaymentPermit",
    ),
    CaseSpec(
        workflow_id="F3",
        title="Fault: negative qty hard-blocked",
        files=("invoice_1009.json",),
        mode="auto_complete",
        expect_status="rejected",
        expect_issue_substr="invalid_quantity",
        forbid_paid=True,
    ),
)
