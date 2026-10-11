"""End-to-end pipeline runner over durable stage queues.

Notes
-----
CLI, workbench, and ``extract_and_validate`` share one queue-drain path.
Do not add a second orchestration engine.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from invoice_automation.adapters.event_log import JsonlEventLog
from invoice_automation.adapters.llm_stub import OfflineLLM
from invoice_automation.adapters.outbox_publisher import OutboxPublisher
from invoice_automation.adapters.payment_mock import MockPaymentGateway
from invoice_automation.adapters.pdf_text import extract_pdf_text
from invoice_automation.adapters.sqlite_inventory import SqliteInventoryRepository
from invoice_automation.adapters.sqlite_queue import SqliteWorkQueue
from invoice_automation.agents.serialization import invoice_from_dict, invoice_to_dict
from invoice_automation.agents.workers import (
    ApprovalWorker,
    IngestionWorker,
    PaymentWorker,
    ValidationWorker,
)
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import Invoice, InvoiceStatus, StageName
from invoice_automation.policy.engine import (
    HARD_BLOCK_PREFIXES,
    configure_policy_engine,
    get_policy_engine,
)
from invoice_automation.saga.payment_saga import PaymentSaga
from invoice_automation.telemetry.metrics import InMemoryMetrics

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "spike" / "schema.sql"


@dataclass
class PipelineResult:
    """Summary for one invoice run.

    Parameters
    ----------
    invoice_id : str
        Business invoice id from the extract stage.
    source_path : str
        Absolute or relative path of the source file.
    status : str
        Final status string (for example ``paid`` or ``rejected``).
    issues : tuple of str
        Validation or policy issue codes.
    approval_reason : str
        VP or rule approval text.
    correlation_id : str
        Run correlation id for event join.
    events : list of dict
        Structured events for this correlation.
    metrics : dict
        Metrics snapshot at completion.
    """

    invoice_id: str
    source_path: str
    status: str
    issues: tuple[str, ...] = ()
    approval_reason: str = ""
    correlation_id: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewDraft:
    """Human-reviewable extract+validate snapshot for the UI desk."""

    correlation_id: str
    source_path: str
    raw_text: str
    invoice: Invoice
    issues: tuple[str, ...]
    confidence: float = 1.0
    self_corrected: bool = False
    notes: str = ""

    @property
    def hard_blocked(self) -> bool:
        """Return True when human Approve must not pay."""
        return any(
            issue.startswith(prefix) for issue in self.issues for prefix in HARD_BLOCK_PREFIXES
        )

    @property
    def review_status(self) -> str:
        if self.hard_blocked:
            return "BLOCKED"
        if self.issues:
            return "NEEDS REVIEW"
        return "CLEAR"


class Pipeline:
    """Build adapters and drain stage queues until work ends.

    Parameters
    ----------
    work_dir : str or Path
        Runtime directory for SQLite DBs, events, and metrics.
    use_grok : bool
        When True, build a live Grok client. When False, use the offline stub.
    event_log_path : str or Path or None
        Optional JSONL path. Default is ``work_dir/events.jsonl``.
    max_steps : int
        Drain budget. Remaining backlog emits ``DrainBudgetExceeded``.
    permit_secret : bytes or str or None
        HMAC secret for PaymentPermit. Default reads ``GALATIQ_PERMIT_SECRET``.
    """

    def __init__(
        self,
        *,
        work_dir: str | Path = ".galatiq_runtime",
        use_grok: bool = False,
        event_log_path: str | Path | None = None,
        max_steps: int = 200,
        permit_secret: bytes | str | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.max_steps = max_steps
        db_path = self.work_dir / "system.db"
        self.db_path = db_path
        self.queue = SqliteWorkQueue(db_path, SCHEMA_PATH)
        self.inventory = SqliteInventoryRepository(self.work_dir / "inventory.db", reseeds=True)
        self.events = JsonlEventLog(event_log_path or self.work_dir / "events.jsonl")
        self.metrics = InMemoryMetrics()
        self.gateway = MockPaymentGateway()
        self.saga = PaymentSaga(db_path, SCHEMA_PATH, self.gateway)
        self.outbox = OutboxPublisher(self.saga, self.events)
        self.policy = configure_policy_engine(db_path=db_path, secret=permit_secret)
        self.llm = self._build_llm(use_grok)

        self.ingestion = IngestionWorker(self.queue, self.llm, self.events, self.metrics)
        self.validation = ValidationWorker(self.queue, self.inventory, self.events, self.metrics)
        self.approval = ApprovalWorker(self.queue, self.llm, self.events, self.metrics)
        self.payment = PaymentWorker(self.queue, self.saga, self.events, self.metrics)

    def _build_llm(self, use_grok: bool) -> Any:
        if use_grok:
            from invoice_automation.adapters.llm_grok import GrokLLM
            from invoice_automation.case_brief import is_live_xai_key

            key = os.getenv("XAI_API_KEY", "")
            if not is_live_xai_key(key):
                raise RuntimeError(
                    "Live Grok requested but XAI_API_KEY is missing/placeholder "
                    '(case brief uses api_key="your_key"). '
                    "Copy .env.example → .env and set a real key, or use --llm=stub."
                )
            return GrokLLM(api_key=key, metrics=self.metrics)
        return OfflineLLM()

    def enqueue_file(self, path: str | Path) -> str:
        path = Path(path)
        correlation_id = str(uuid4())
        invoice_hint = path.stem
        self.queue.enqueue(
            StageName.INGESTION,
            {"path": str(path.resolve()), "invoice_id": invoice_hint},
            idempotency_key=f"ing:{path.resolve()}:{correlation_id}",
            correlation_id=correlation_id,
        )
        self.events.emit(
            "InvoiceReceived",
            correlation_id,
            invoice_hint,
            {"path": str(path)},
            stage=StageName.INGESTION.value,
        )
        return correlation_id

    def drain(
        self,
        max_steps: int | None = None,
        *,
        stages: Iterable[StageName] | None = None,
    ) -> None:
        """Process queued work until idle or the step budget ends.

        Parameters
        ----------
        max_steps : int or None
            Override for ``self.max_steps``.
        stages : iterable of StageName or None
            Stages to drain. Default drains all stages.
        """
        budget = self.max_steps if max_steps is None else max_steps
        allowed = set(stages) if stages is not None else set(StageName)
        for _ in range(1, budget + 1):
            progressed = False
            if StageName.INGESTION in allowed:
                progressed |= self.ingestion.process_one()
            if StageName.VALIDATION in allowed:
                progressed |= self.validation.process_one()
            if StageName.APPROVAL in allowed:
                progressed |= self.approval.process_one()
            if StageName.PAYMENT in allowed:
                progressed |= self.payment.process_one()
            if not progressed:
                break
        else:
            # Exhausted budget with possible backlog.
            depth = self.queue.depth()
            if depth > 0:
                self.events.emit(
                    "DrainBudgetExceeded",
                    "system",
                    "system",
                    {
                        "max_steps": budget,
                        "queue_depth": depth,
                        "stages": sorted(s.value for s in allowed),
                    },
                    stage="orchestration",
                )
                self.metrics.incr_error("orchestration", "DrainBudgetExceeded")

        self.outbox.flush()
        self.metrics.persist(self.work_dir / "metrics_snapshot.json")

    def process_file(self, path: str | Path) -> PipelineResult:
        """Enqueue one invoice file and drain all stages.

        Parameters
        ----------
        path : str or Path
            Path to an invoice file.

        Returns
        -------
        PipelineResult
            Final status, issues, events, and metrics for the run.
        """
        path = Path(path)
        correlation_id = self.enqueue_file(path)
        self.drain()
        return self._summarize(path, correlation_id)

    def process_directory(self, directory: str | Path) -> list[PipelineResult]:
        directory = Path(directory)
        suffixes = {".txt", ".json", ".csv", ".xml", ".pdf"}
        files = sorted(
            p for p in directory.iterdir() if p.suffix.lower() in suffixes and p.is_file()
        )
        stems_with_txt = {p.stem for p in files if p.suffix.lower() == ".txt"}
        selected = [
            p for p in files if not (p.suffix.lower() == ".pdf" and p.stem in stems_with_txt)
        ]
        results: list[PipelineResult] = []
        for path in selected:
            results.append(self.process_file(path))
        return results

    def extract_and_validate(self, path: str | Path) -> ReviewDraft:
        """Run ingestion + validation via durable queues, then pause for review.

        Auto-enqueued approval work for this correlation is dropped so HITL owns
        the next step (same adapters/events as CLI `process_file`).
        """
        path = Path(path).resolve()
        correlation_id = self.enqueue_file(path)
        self.drain(
            stages=(StageName.INGESTION, StageName.VALIDATION),
        )
        self.queue.drop_correlation(StageName.APPROVAL, correlation_id)
        return self._review_draft_from_events(path, correlation_id)

    def _review_draft_from_events(self, path: Path, correlation_id: str) -> ReviewDraft:
        events = [e for e in self.events.read_all() if e.get("correlation_id") == correlation_id]
        raw_text = _read_source(path)
        invoice_payload: dict[str, Any] | None = None
        issues: tuple[str, ...] = ()
        confidence = 0.9
        self_corrected = False
        notes = ""

        for event in events:
            et = event.get("event_type")
            payload = event.get("payload") or {}
            if et == "IngestionFailed":
                raise ExtractionError(str(payload.get("error") or "ingestion failed"))
            if et == "InvoiceExtracted":
                invoice_payload = payload.get("invoice") or invoice_payload
                self_corrected = bool(payload.get("self_corrected", self_corrected))
                notes = str(payload.get("notes") or notes)
                confidence = float(payload.get("confidence") or confidence)
            if et == "InvoiceValidated":
                invoice_payload = payload.get("invoice") or invoice_payload
                issues = ()
            if et == "InvoiceRejected" and payload.get("stage") == "validation":
                invoice_payload = payload.get("invoice") or invoice_payload
                issues = tuple(payload.get("issues") or ())

        if not invoice_payload:
            raise ExtractionError("extract_and_validate: no InvoiceExtracted event")

        invoice = invoice_from_dict(invoice_payload)
        invoice = invoice.with_updates(
            correlation_id=correlation_id,
            source_path=str(path),
            issues=issues,
            status=InvoiceStatus.REJECTED if issues else InvoiceStatus.VALIDATED,
        )
        return ReviewDraft(
            correlation_id=correlation_id,
            source_path=str(path),
            raw_text=raw_text,
            invoice=invoice,
            issues=issues,
            confidence=confidence,
            self_corrected=self_corrected,
            notes=notes,
        )

    def auto_approve(self, draft: ReviewDraft) -> PipelineResult:
        """Run VP approval agent and payment when approved."""
        invoice = draft.invoice
        if draft.issues and not invoice.is_high_value:
            self.events.emit(
                "InvoiceRejected",
                draft.correlation_id,
                invoice.invoice_id,
                {
                    "reason": f"Rejected due to issues: {', '.join(draft.issues)}",
                    "reflected": False,
                },
                stage=StageName.APPROVAL.value,
            )
            self.metrics.incr_outcome("rejected")
            self.metrics.persist(self.work_dir / "metrics_snapshot.json")
            return self._summarize(Path(draft.source_path), draft.correlation_id)

        self.queue.enqueue(
            StageName.APPROVAL,
            {"invoice": invoice_to_dict(invoice.with_updates(status=InvoiceStatus.VALIDATED))},
            idempotency_key=f"appr:{invoice.invoice_id}:{draft.correlation_id}",
            correlation_id=draft.correlation_id,
        )
        self.drain(stages=(StageName.APPROVAL, StageName.PAYMENT))
        return self._summarize(Path(draft.source_path), draft.correlation_id)

    def human_approve(
        self,
        draft: ReviewDraft,
        *,
        permit: Any = None,
        actor: str = "analyst",
        allow_soft_override: bool = False,
    ) -> PipelineResult:
        """Approve → payment only with a verified PaymentPermit (non-LLM fence)."""
        from invoice_automation.policy.engine import PaymentPermit

        policy = get_policy_engine()
        invoice = draft.invoice.with_updates(
            status=InvoiceStatus.APPROVED,
            approval_reason=draft.notes or "Approved with payment permit",
            issues=draft.issues,
        )
        if permit is None:
            permit = policy.issue_permit(
                invoice,
                actor=actor,
                open_issues=draft.issues,
                allow_soft_override=allow_soft_override,
            )
        else:
            if isinstance(permit, dict):
                permit = PaymentPermit.from_dict(permit)
            policy.verify_permit(permit, invoice, open_issues=draft.issues, consume=False)

        self.events.emit(
            "InvoiceApproved",
            draft.correlation_id,
            invoice.invoice_id,
            {
                "reason": invoice.approval_reason,
                "reflected": False,
                "human": True,
                "permit_nonce": permit.nonce,
                "actor": permit.actor,
            },
            stage=StageName.APPROVAL.value,
        )
        self.queue.enqueue(
            StageName.PAYMENT,
            {"invoice": invoice_to_dict(invoice), "permit": permit.to_dict()},
            idempotency_key=f"payq:{invoice.invoice_id}:{draft.correlation_id}",
            correlation_id=draft.correlation_id,
        )
        self.drain(stages=(StageName.PAYMENT,))
        return self._summarize(Path(draft.source_path), draft.correlation_id)

    def human_reject(self, draft: ReviewDraft, reason: str = "Human rejected") -> PipelineResult:
        """Terminal human reject with audit event; no payment."""
        self.events.emit(
            "InvoiceRejected",
            draft.correlation_id,
            draft.invoice.invoice_id,
            {"reason": reason, "reflected": False, "human": True},
            stage=StageName.APPROVAL.value,
        )
        self.metrics.incr_outcome("rejected")
        self.metrics.persist(self.work_dir / "metrics_snapshot.json")
        return self._summarize(Path(draft.source_path), draft.correlation_id)

    def _summarize(self, path: Path, correlation_id: str) -> PipelineResult:
        events = [e for e in self.events.read_all() if e.get("correlation_id") == correlation_id]
        invoice_id = path.stem
        status = "unknown"
        issues: tuple[str, ...] = ()
        reason = ""
        for event in events:
            invoice_id = event.get("invoice_id") or invoice_id
            et = event.get("event_type")
            payload = event.get("payload") or {}
            if et == "InvoiceRejected":
                status = InvoiceStatus.REJECTED.value
                if "issues" in payload:
                    issues = tuple(payload.get("issues") or ())
                reason = str(payload.get("reason") or reason)
            elif et == "PaymentSucceeded":
                status = InvoiceStatus.PAID.value
            elif et == "PaymentFailed":
                # Do not leave status stuck on approved when pay did not complete.
                status = "failed"
                reason = str(payload.get("error") or reason)
            elif et == "InvoiceApproved" and status not in {
                InvoiceStatus.PAID.value,
                "failed",
            }:
                status = InvoiceStatus.APPROVED.value
                reason = str(payload.get("reason") or reason)
            elif et == "IngestionFailed" and status == "unknown":
                status = "failed"
                reason = str(payload.get("error") or reason)
            elif et == "InvoiceValidated" and status == "unknown":
                status = InvoiceStatus.VALIDATED.value
        return PipelineResult(
            invoice_id=str(invoice_id),
            source_path=str(path),
            status=status,
            issues=issues,
            approval_reason=reason,
            correlation_id=correlation_id,
            events=events,
            metrics=self.metrics.snapshot(),
        )


def _read_source(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="replace")
