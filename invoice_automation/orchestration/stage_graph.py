"""Explicit conditional stage graph for pipeline drain.

Notes
-----
Workers still own enqueue side-effects (validation only enqueues approval when
clean). ``Pipeline.drain`` uses this graph to pick the next ready stage in
wavefront order instead of round-robin every stage each tick.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from invoice_automation.domain.models import StageName

# Terminal sinks (not durable queues).
TERMINAL_REJECT = "REJECT"
TERMINAL_PAID = "PAID"
TERMINAL_RECONCILE = "RECONCILE"

STAGE_ORDER: tuple[StageName, ...] = (
    StageName.INGESTION,
    StageName.VALIDATION,
    StageName.APPROVAL,
    StageName.PAYMENT,
)


@dataclass(frozen=True)
class GraphEdge:
    """One conditional edge on the orchestration graph.

    Parameters
    ----------
    source : str
        Stage name or ``START``.
    target : str
        Next stage name or a terminal sink.
    when : str
        Human-readable condition label (must match worker behavior).
    """

    source: str
    target: str
    when: str


# Canonical edges. Keep in sync with workers + docs/architecture.md.
EDGES: tuple[GraphEdge, ...] = (
    GraphEdge("START", StageName.INGESTION.value, "file_enqueued"),
    GraphEdge(StageName.INGESTION.value, StageName.VALIDATION.value, "extracted"),
    GraphEdge(StageName.VALIDATION.value, TERMINAL_REJECT, "issues_nonempty"),
    GraphEdge(StageName.VALIDATION.value, StageName.APPROVAL.value, "issues_empty"),
    GraphEdge(StageName.APPROVAL.value, TERMINAL_REJECT, "vp_rejected"),
    GraphEdge(
        StageName.APPROVAL.value,
        StageName.PAYMENT.value,
        "approved_with_permit",
    ),
    GraphEdge(StageName.PAYMENT.value, TERMINAL_PAID, "gateway_ok_stock_ok"),
    GraphEdge(
        StageName.PAYMENT.value,
        TERMINAL_RECONCILE,
        "gateway_ok_stock_fail",
    ),
)


@dataclass
class PipelineState:
    """Mutable orchestration cursor for one drain session.

    Parameters
    ----------
    correlation_id : str
        Optional correlation for the active file.
    active_stage : StageName or None
        Stage selected for the current step.
    last_edge : str
        Last ``when`` label applied (audit).
    terminal : str
        Terminal sink when the invoice finished (REJECT/PAID/RECONCILE).
    steps : int
        Drain steps consumed.
    transitions : list of str
        Ordered ``source->target`` edge records for the session.
    """

    correlation_id: str = ""
    active_stage: StageName | None = None
    last_edge: str = ""
    terminal: str = ""
    steps: int = 0
    transitions: list[str] | None = None

    def __post_init__(self) -> None:
        if self.transitions is None:
            self.transitions = []

    def record(self, source: str, target: str, when: str) -> None:
        """Append one edge transition."""
        assert self.transitions is not None
        self.last_edge = when
        self.transitions.append(f"{source}->{target}:{when}")
        if target in {TERMINAL_REJECT, TERMINAL_PAID, TERMINAL_RECONCILE}:
            self.terminal = target


def edge_map() -> dict[str, list[GraphEdge]]:
    """Group edges by source stage name."""
    out: dict[str, list[GraphEdge]] = {}
    for edge in EDGES:
        out.setdefault(edge.source, []).append(edge)
    return out


def validate_graph() -> None:
    """Raise ``ValueError`` when the graph is incomplete or inconsistent.

    Notes
    -----
    Strict checks for CI: every durable stage appears as a source; payment
    and validation have both success and failure edges.
    """
    sources = {e.source for e in EDGES}
    for stage in STAGE_ORDER:
        if stage.value not in sources:
            raise ValueError(f"stage {stage.value!r} has no outgoing edges")
    by_src = edge_map()
    val_targets = {e.target for e in by_src[StageName.VALIDATION.value]}
    if TERMINAL_REJECT not in val_targets or StageName.APPROVAL.value not in val_targets:
        raise ValueError("validation must edge to REJECT and approval")
    appr_targets = {e.target for e in by_src[StageName.APPROVAL.value]}
    if TERMINAL_REJECT not in appr_targets or StageName.PAYMENT.value not in appr_targets:
        raise ValueError("approval must edge to REJECT and payment")
    pay_targets = {e.target for e in by_src[StageName.PAYMENT.value]}
    if TERMINAL_PAID not in pay_targets or TERMINAL_RECONCILE not in pay_targets:
        raise ValueError("payment must edge to PAID and RECONCILE")


def select_ready_stage(
    depth_for: Callable[[StageName], int],
    allowed: Iterable[StageName],
) -> StageName | None:
    """Pick the upstream-most ready stage (wavefront).

    Parameters
    ----------
    depth_for : callable
        Returns pending queue depth for one stage.
    allowed : iterable of StageName
        Stages permitted in this drain.

    Returns
    -------
    StageName or None
        Next stage to run, or None when idle.
    """
    allowed_set = set(allowed)
    for stage in STAGE_ORDER:
        if stage in allowed_set and depth_for(stage) > 0:
            return stage
    return None
