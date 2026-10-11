"""Stage workers: ingestion, validation, approval, payment.

Notes
-----
Each worker takes at most one message per ``process_one`` call.
``Pipeline.drain`` runs the workers until the queues are idle or the
step budget ends. Grok auth failures must not become soft ingest errors.
They raise ``GrokAuthError`` again.
"""

from __future__ import annotations

import time
from pathlib import Path

from invoice_automation.adapters.parsers import normalize_invoice_id
from invoice_automation.adapters.pdf_text import extract_pdf_text
from invoice_automation.agents.serialization import invoice_from_dict, invoice_to_dict
from invoice_automation.domain.exceptions import (
    ExtractionError,
    InvoiceDomainError,
    PaymentError,
    ValidationError,
)
from invoice_automation.domain.models import InvoiceStatus, StageName
from invoice_automation.ports.contracts import (
    EventSink,
    InventoryRepository,
    LLMClient,
    MetricsCollector,
    WorkQueue,
)
from invoice_automation.saga.payment_saga import PaymentSaga


def _read_source(path: str | Path) -> str:
    """Read invoice bytes as text. PDFs go through the PDF text extractor."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return extract_pdf_text(p)
    return p.read_text(encoding="utf-8", errors="replace")


class IngestionWorker:
    """Pull one ingestion job, extract structured invoice data, enqueue validation.

    Parameters
    ----------
    queue : WorkQueue
        Durable stage queue.
    llm : LLMClient
        Stub or Grok extractor.
    events : EventSink
        Append-only event log.
    metrics : MetricsCollector
        Latency and error counters.
    """

    def __init__(
        self,
        queue: WorkQueue,
        llm: LLMClient,
        events: EventSink,
        metrics: MetricsCollector,
    ) -> None:
        self.queue = queue
        self.llm = llm
        self.events = events
        self.metrics = metrics

    def process_one(self) -> bool:
        """Process one ingestion message.

        Returns
        -------
        bool
            True if a message was claimed (success or failure). False if idle.

        Raises
        ------
        GrokAuthError
            When the live LLM rejects the API key (fail closed; no parser fallback).
        """
        msg = self.queue.dequeue(StageName.INGESTION)
        if msg is None:
            return False
        started = time.perf_counter()
        payload = msg["payload"]
        path = payload["path"]
        correlation_id = msg["correlation_id"]
        try:
            raw = _read_source(path)
            result = self.llm.extract(raw, path)
            invoice = result.invoice.with_updates(
                correlation_id=correlation_id,
                source_path=str(path),
            )
            self.events.emit(
                "InvoiceExtracted",
                correlation_id,
                invoice.invoice_id,
                {
                    "vendor": invoice.vendor,
                    "amount": str(invoice.amount),
                    "self_corrected": result.self_corrected,
                    "notes": result.notes,
                    "invoice": invoice_to_dict(invoice),
                    "confidence": result.raw_confidence,
                },
                stage=StageName.INGESTION.value,
            )
            self.queue.enqueue(
                StageName.VALIDATION,
                {"invoice": invoice_to_dict(invoice)},
                idempotency_key=f"val:{invoice.invoice_id}:{invoice.correlation_id}",
                correlation_id=correlation_id,
            )
            self.queue.ack(msg["id"])
            self.metrics.incr_rate(StageName.INGESTION.value, "success")
        except Exception as exc:
            # Auth must surface to the CLI; do not bury it as IngestionFailed.
            from invoice_automation.adapters.llm_grok import GrokAuthError

            if isinstance(exc, GrokAuthError):
                self.queue.fail(msg["id"], reason=str(exc))
                raise
            from invoice_automation.resilience.policies import CircuitOpenError

            if isinstance(
                exc,
                (ExtractionError, ValidationError, OSError, ValueError, CircuitOpenError),
            ):
                self.metrics.incr_error(StageName.INGESTION.value, type(exc).__name__)
                self.events.emit(
                    "IngestionFailed",
                    correlation_id,
                    str(payload.get("invoice_id", Path(path).stem)),
                    {"error": str(exc)},
                    stage=StageName.INGESTION.value,
                )
                self.queue.fail(msg["id"], reason=str(exc))
            else:
                self.metrics.incr_error(StageName.INGESTION.value, type(exc).__name__)
                self.queue.fail(msg["id"], reason=str(exc))
                raise
        finally:
            self.metrics.observe_latency(StageName.INGESTION.value, time.perf_counter() - started)
        return True


class ValidationWorker:
    """Check inventory and invariants; reject hard failures or enqueue approval.

    Parameters
    ----------
    queue : WorkQueue
        Durable stage queue.
    inventory : InventoryRepository
        SKU / stock checks.
    events : EventSink
        Append-only event log.
    metrics : MetricsCollector
        Latency and outcome counters.
    """

    def __init__(
        self,
        queue: WorkQueue,
        inventory: InventoryRepository,
        events: EventSink,
        metrics: MetricsCollector,
    ) -> None:
        self.queue = queue
        self.inventory = inventory
        self.events = events
        self.metrics = metrics

    def process_one(self) -> bool:
        """Validate one invoice.

        Returns
        -------
        bool
            True if a message was claimed. False if the queue is idle.

        Notes
        -----
        Any issue code rejects in the auto CLI path. Soft issues can later be
        overridden only via an explicit PaymentPermit in the workbench.
        """
        msg = self.queue.dequeue(StageName.VALIDATION)
        if msg is None:
            return False
        started = time.perf_counter()
        correlation_id = msg["correlation_id"]
        try:
            from invoice_automation.policy.invariants import collect_invariant_issues

            invoice = invoice_from_dict(msg["payload"]["invoice"])
            issues = self.inventory.check_availability(invoice.items)
            issues.extend(collect_invariant_issues(invoice))
            # Deduplicate while keeping order.
            seen: set[str] = set()
            uniq: list[str] = []
            for issue in issues:
                if issue not in seen:
                    seen.add(issue)
                    uniq.append(issue)
            issues = uniq

            if issues:
                invoice = invoice.with_updates(
                    status=InvoiceStatus.REJECTED,
                    issues=tuple(issues),
                    approval_reason=f"Validation failed: {', '.join(issues)}",
                )
                self.events.emit(
                    "InvoiceRejected",
                    correlation_id,
                    invoice.invoice_id,
                    {
                        "issues": issues,
                        "stage": "validation",
                        "invoice": invoice_to_dict(invoice),
                    },
                    stage=StageName.VALIDATION.value,
                )
                self.metrics.incr_rate(StageName.VALIDATION.value, "rejected")
                self.metrics.incr_outcome("rejected")
            else:
                invoice = invoice.with_updates(status=InvoiceStatus.VALIDATED, issues=())
                self.events.emit(
                    "InvoiceValidated",
                    correlation_id,
                    invoice.invoice_id,
                    {"invoice": invoice_to_dict(invoice)},
                    stage=StageName.VALIDATION.value,
                )
                self.queue.enqueue(
                    StageName.APPROVAL,
                    {"invoice": invoice_to_dict(invoice)},
                    idempotency_key=f"appr:{invoice.invoice_id}:{invoice.correlation_id}",
                    correlation_id=correlation_id,
                )
                self.metrics.incr_rate(StageName.VALIDATION.value, "success")
            self.queue.ack(msg["id"])
            msg["payload"]["invoice"] = invoice_to_dict(invoice)
        except (ValidationError, InvoiceDomainError, KeyError, TypeError, ValueError) as exc:
            self.metrics.incr_error(StageName.VALIDATION.value, type(exc).__name__)
            self.queue.fail(msg["id"], reason=str(exc))
        except Exception:
            self.metrics.incr_error(StageName.VALIDATION.value, "unexpected")
            self.queue.fail(msg["id"], reason="unexpected validation error")
            raise
        finally:
            self.metrics.observe_latency(StageName.VALIDATION.value, time.perf_counter() - started)
        return True


class ApprovalWorker:
    """Run VP or system approval. Issue a PaymentPermit. Enqueue payment.

    Parameters
    ----------
    queue : WorkQueue
        Durable stage queue.
    llm : LLMClient
        Approver. Stub uses rules. Grok uses reflection for high value.
    events : EventSink
        Append-only event log.
    metrics : MetricsCollector
        Approval and reflection counters.

    Notes
    -----
    The CLI has no interactive human reject. Rejection happens when:

    * validation left issues, or
    * the LLM or stub returns ``approved=False``, or
    * ``PolicyEngine.issue_permit`` denies payment.

    Human reject and escalate live in the FastAPI workbench, not in the CLI.
    """

    def __init__(
        self,
        queue: WorkQueue,
        llm: LLMClient,
        events: EventSink,
        metrics: MetricsCollector,
    ) -> None:
        self.queue = queue
        self.llm = llm
        self.events = events
        self.metrics = metrics

    def process_one(self) -> bool:
        """Approve or reject one invoice and attach a permit when approved.

        Returns
        -------
        bool
            True if a message was claimed. False if idle.
        """
        msg = self.queue.dequeue(StageName.APPROVAL)
        if msg is None:
            return False
        started = time.perf_counter()
        correlation_id = msg["correlation_id"]
        try:
            invoice = invoice_from_dict(msg["payload"]["invoice"])
            decision = self.llm.approve(invoice)
            audit = getattr(self.llm, "last_approve_audit", None)
            if isinstance(audit, dict) and audit:
                self.events.emit(
                    "ApprovalAudit",
                    correlation_id,
                    invoice.invoice_id,
                    audit,
                    stage=StageName.APPROVAL.value,
                )
            if decision.approved:
                from invoice_automation.policy.engine import PolicyError, get_policy_engine

                invoice = invoice.with_updates(
                    status=InvoiceStatus.APPROVED,
                    approval_reason=decision.reason,
                )
                try:
                    # LLM text never authorizes pay — only a verified permit does.
                    permit = get_policy_engine().issue_permit(
                        invoice,
                        actor="vp_agent" if invoice.is_high_value else "system",
                        open_issues=invoice.issues,
                        allow_soft_override=False,
                    )
                except PolicyError as exc:
                    invoice = invoice.with_updates(
                        status=InvoiceStatus.REJECTED,
                        approval_reason=f"Policy denied payment: {exc}",
                    )
                    self.events.emit(
                        "InvoiceRejected",
                        correlation_id,
                        invoice.invoice_id,
                        {"reason": str(exc), "reflected": decision.reflected},
                        stage=StageName.APPROVAL.value,
                    )
                    self.metrics.incr_rate(StageName.APPROVAL.value, "rejected")
                    self.metrics.incr_outcome("rejected")
                    if decision.reflected:
                        self.metrics.incr_vp_reflection("reject")
                    self.queue.ack(msg["id"])
                    return True
                self.events.emit(
                    "InvoiceApproved",
                    correlation_id,
                    invoice.invoice_id,
                    {
                        "reason": decision.reason,
                        "reflected": decision.reflected,
                        "permit_nonce": permit.nonce,
                    },
                    stage=StageName.APPROVAL.value,
                )
                if decision.reflected:
                    self.metrics.incr_vp_reflection("approve" if decision.approved else "reject")
                self.queue.enqueue(
                    StageName.PAYMENT,
                    {"invoice": invoice_to_dict(invoice), "permit": permit.to_dict()},
                    idempotency_key=f"payq:{invoice.invoice_id}:{invoice.correlation_id}",
                    correlation_id=correlation_id,
                )
                self.metrics.incr_rate(StageName.APPROVAL.value, "approved")
            else:
                invoice = invoice.with_updates(
                    status=InvoiceStatus.REJECTED,
                    approval_reason=decision.reason,
                )
                self.events.emit(
                    "InvoiceRejected",
                    correlation_id,
                    invoice.invoice_id,
                    {"reason": decision.reason, "reflected": decision.reflected},
                    stage=StageName.APPROVAL.value,
                )
                self.metrics.incr_rate(StageName.APPROVAL.value, "rejected")
                self.metrics.incr_outcome("rejected")
                if decision.reflected:
                    self.metrics.incr_vp_reflection("reject")
            self.queue.ack(msg["id"])
        except (InvoiceDomainError, KeyError, TypeError, ValueError) as exc:
            self.metrics.incr_error(StageName.APPROVAL.value, type(exc).__name__)
            self.queue.fail(msg["id"], reason=str(exc))
        except Exception:
            self.metrics.incr_error(StageName.APPROVAL.value, "unexpected")
            self.queue.fail(msg["id"], reason="unexpected approval error")
            raise
        finally:
            self.metrics.observe_latency(StageName.APPROVAL.value, time.perf_counter() - started)
        return True


class PaymentWorker:
    """Verify the PaymentPermit. Run the payment saga. Emit success or failure.

    Parameters
    ----------
    queue : WorkQueue
        Durable stage queue.
    saga : PaymentSaga
        Idempotent mock payment and outbox writer.
    events : EventSink
        Append-only event log.
    metrics : MetricsCollector
        Payment outcome counters.

    Notes
    -----
    Missing or bad permits refuse payment. Policy and payment errors both
    emit ``PaymentFailed``. The CLI status does not stay on ``approved``.
    """

    def __init__(
        self,
        queue: WorkQueue,
        saga: PaymentSaga,
        events: EventSink,
        metrics: MetricsCollector,
    ) -> None:
        self.queue = queue
        self.saga = saga
        self.events = events
        self.metrics = metrics

    def process_one(self) -> bool:
        """Pay one permitted invoice.

        Returns
        -------
        bool
            True if a message was claimed. False if idle.
        """
        msg = self.queue.dequeue(StageName.PAYMENT)
        if msg is None:
            return False
        started = time.perf_counter()
        correlation_id = msg["correlation_id"]
        invoice_id = str(
            (msg["payload"].get("invoice") or {}).get("invoice_id")
            or msg["payload"].get("invoice_id")
            or "unknown"
        )
        try:
            from invoice_automation.policy.engine import PolicyError, get_policy_engine

            invoice = invoice_from_dict(msg["payload"]["invoice"])
            invoice_id = invoice.invoice_id
            permit_data = msg["payload"].get("permit")
            if not permit_data:
                raise PolicyError("Payment node refused: missing PaymentPermit")
            engine = get_policy_engine()
            # Verify first without consume. If pay fails, the queue can retry
            # with the same permit. Consume only after a successful pay.
            engine.verify_permit(
                permit_data,
                invoice,
                open_issues=invoice.issues,
                consume=False,
            )
            # Key saga by business INV- id; keep file stem as audit metadata only.
            source_stem = Path(invoice.source_path).stem or ""
            payment_id = normalize_invoice_id(invoice.invoice_id, fallback=source_stem)
            result = self.saga.pay(
                invoice_id=payment_id,
                vendor=invoice.vendor,
                amount=invoice.amount,
                correlation_id=correlation_id,
                idempotency_key=f"pay:{payment_id}",
                items=invoice.items,
                source_stem=source_stem,
            )
            # Saga returned reconcile. Do not mark paid. Do not consume the permit.
            if result.status == "reconcile":
                self.events.emit(
                    "PaymentStockReconcile",
                    correlation_id,
                    invoice.invoice_id,
                    {
                        "error": "stock_reconcile_required:replay",
                        "transaction_id": result.transaction_id,
                        "payment_id": payment_id,
                        "source_stem": source_stem,
                    },
                    stage=StageName.PAYMENT.value,
                )
                self.metrics.incr_rate(StageName.PAYMENT.value, "reconcile")
                self.metrics.incr_outcome("reconcile")
                self.queue.fail(msg["id"], reason="stock_reconcile_required:replay")
                return True
            engine.verify_permit(
                permit_data,
                invoice,
                open_issues=invoice.issues,
                consume=True,
            )
            invoice = invoice.with_updates(status=InvoiceStatus.PAID)
            self.events.emit(
                "PaymentSucceeded",
                correlation_id,
                invoice.invoice_id,
                {
                    "transaction_id": result.transaction_id,
                    "amount": str(result.amount),
                    "vendor": result.vendor,
                    "payment_id": payment_id,
                    "source_stem": source_stem,
                },
                stage=StageName.PAYMENT.value,
            )
            self.metrics.incr_rate(StageName.PAYMENT.value, "paid")
            self.metrics.incr_outcome("paid")
            self.queue.ack(msg["id"])
        except (PaymentError, ValidationError) as exc:
            # PolicyError subclasses ValidationError.
            self.metrics.incr_error(StageName.PAYMENT.value, type(exc).__name__)
            err = str(exc)
            event_type = (
                "PaymentStockReconcile"
                if err.startswith("stock_reconcile_required:")
                else "PaymentFailed"
            )
            if event_type == "PaymentStockReconcile":
                self.metrics.incr_rate(StageName.PAYMENT.value, "reconcile")
                self.metrics.incr_outcome("reconcile")
            self.events.emit(
                event_type,
                correlation_id,
                invoice_id,
                {"error": err},
                stage=StageName.PAYMENT.value,
            )
            self.queue.fail(msg["id"], reason=err)
        except Exception:
            self.metrics.incr_error(StageName.PAYMENT.value, "unexpected")
            self.queue.fail(msg["id"], reason="unexpected payment error")
            raise
        finally:
            self.metrics.observe_latency(StageName.PAYMENT.value, time.perf_counter() - started)
        return True
