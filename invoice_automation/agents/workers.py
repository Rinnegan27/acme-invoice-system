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
from collections.abc import Callable
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
from invoice_automation.domain.models import ApprovalDecision, Invoice, InvoiceStatus, StageName
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
            # Fail closed on document Qty markers even if the LLM coerces ints.
            from invoice_automation.adapters.parsers import assert_raw_quantity_integrity

            assert_raw_quantity_integrity(raw)
            result = self.llm.extract(raw, path)
            from invoice_automation.policy.sku_resolve import (
                resolve_line_items,
                soft_issues_from_source_items,
                undo_abbreviation_expansions,
                undo_digit_sku_expansions,
            )

            # Undo silent LLM abbrev expansion; resolver re-maps with VP soft escalate.
            items = undo_abbreviation_expansions(raw, result.invoice.items)
            # Digit-bearing source tokens are not fat-finger fixes (Widg3tA → hard reject).
            items = undo_digit_sku_expansions(raw, items)
            resolved_items, resolve_soft = resolve_line_items(items)
            # Alias / abbrev / unique-close Item: phrases escalate to VP (W-A, Widget Alpha).
            source_soft = soft_issues_from_source_items(raw, resolved_items)
            soft = list(dict.fromkeys([*resolve_soft, *source_soft]))
            prior_issues = list(result.invoice.issues)
            merged = tuple(dict.fromkeys([*prior_issues, *soft]))
            invoice = result.invoice.with_updates(
                correlation_id=correlation_id,
                source_path=str(path),
                items=resolved_items,
                issues=merged,
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
    system_db_path : path or None
        ``system.db`` for vendor split / payment-history checks.
    """

    def __init__(
        self,
        queue: WorkQueue,
        inventory: InventoryRepository,
        events: EventSink,
        metrics: MetricsCollector,
        *,
        system_db_path: str | Path | None = None,
    ) -> None:
        self.queue = queue
        self.inventory = inventory
        self.events = events
        self.metrics = metrics
        self.system_db_path = Path(system_db_path) if system_db_path else None

    def process_one(self) -> bool:
        """Validate one invoice.

        Returns
        -------
        bool
            True if a message was claimed. False if the queue is idle.

        Notes
        -----
        Hard issues reject. Soft escalations (SKU typo, vendor split) go to VP.
        """
        msg = self.queue.dequeue(StageName.VALIDATION)
        if msg is None:
            return False
        started = time.perf_counter()
        correlation_id = msg["correlation_id"]
        try:
            from invoice_automation.policy.invariants import (
                collect_invariant_issues,
                partition_soft_escalation_issues,
            )
            from invoice_automation.policy.vendor_risk import detect_vendor_split_risk

            invoice = invoice_from_dict(msg["payload"]["invoice"])
            issues = list(invoice.issues)
            prior_items = None
            if self.system_db_path is not None:
                from invoice_automation.saga.payment_saga import load_succeeded_line_items

                prior_items = load_succeeded_line_items(self.system_db_path, invoice.invoice_id)
            issues.extend(self.inventory.check_availability(invoice.items, prior_items=prior_items))
            issues.extend(collect_invariant_issues(invoice))
            issues.extend(
                detect_vendor_split_risk(
                    invoice.vendor,
                    invoice.amount,
                    db_path=self.system_db_path,
                    invoice_id=invoice.invoice_id,
                )
            )
            # Deduplicate while keeping order.
            seen: set[str] = set()
            uniq: list[str] = []
            for issue in issues:
                if issue not in seen:
                    seen.add(issue)
                    uniq.append(issue)
            issues = uniq
            hard_or_other, soft_escalations = partition_soft_escalation_issues(issues)

            if hard_or_other:
                invoice = invoice.with_updates(
                    status=InvoiceStatus.REJECTED,
                    issues=tuple(issues),
                    approval_reason=f"Validation failed: {', '.join(hard_or_other)}",
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
                # Soft escalations (SKU typo / vendor split) go to VP, not auto-pay.
                invoice = invoice.with_updates(
                    status=InvoiceStatus.VALIDATED,
                    issues=tuple(soft_escalations),
                )
                self.events.emit(
                    "InvoiceValidated",
                    correlation_id,
                    invoice.invoice_id,
                    {
                        "invoice": invoice_to_dict(invoice),
                        "soft_escalations": soft_escalations,
                    },
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
    """Run human / VP / system approval. Issue a PaymentPermit. Enqueue payment.

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
        human_gate : callable or None
        Optional CLI/desk callback ``(Invoice) -> str`` returning
        ``approve``, ``reject``, or ``escalate``. Invoked when high-value or
        soft escalations require scrutiny. ``escalate`` defers to the
        automated VP agent (``llm.approve``).

    Notes
    -----
    Rejection also happens when validation left hard issues, the LLM returns
    ``approved=False``, or ``PolicyEngine.issue_permit`` denies payment.
    The FastAPI Control Centre remains the full desk path; the CLI gate covers
    the same approve / reject / escalate choices for interactive runs.
    """

    def __init__(
        self,
        queue: WorkQueue,
        llm: LLMClient,
        events: EventSink,
        metrics: MetricsCollector,
        *,
        human_gate: Callable[[Invoice], str] | None = None,
    ) -> None:
        self.queue = queue
        self.llm = llm
        self.events = events
        self.metrics = metrics
        self.human_gate = human_gate

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
            from invoice_automation.policy.invariants import (
                is_soft_escalation,
                partition_soft_escalation_issues,
            )

            invoice = invoice_from_dict(msg["payload"]["invoice"])
            _other, soft = partition_soft_escalation_issues(invoice.issues)
            needs_scrutiny = invoice.is_high_value or bool(soft)
            human_action: str | None = None
            decision: ApprovalDecision
            if needs_scrutiny and self.human_gate is not None:
                human_action = str(self.human_gate(invoice))
                if human_action == "approve":
                    decision = ApprovalDecision(
                        approved=True,
                        reason="Human approved via CLI (HITL)",
                        reflected=True,
                    )
                elif human_action == "reject":
                    decision = ApprovalDecision(
                        approved=False,
                        reason="Human rejected via CLI (HITL)",
                        reflected=True,
                    )
                else:
                    # escalate → automated VP agent
                    human_action = "escalate"
                    decision = self.llm.approve(invoice)
            else:
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
            if human_action is not None:
                self.events.emit(
                    "HumanApprovalGate",
                    correlation_id,
                    invoice.invoice_id,
                    {
                        "action": human_action,
                        "high_value": invoice.is_high_value,
                        "soft": list(soft),
                    },
                    stage=StageName.APPROVAL.value,
                )
            if decision.approved:
                from invoice_automation.policy.engine import PolicyError, get_policy_engine

                invoice = invoice.with_updates(
                    status=InvoiceStatus.APPROVED,
                    approval_reason=decision.reason,
                )
                try:
                    needs_vp = invoice.is_high_value or bool(soft)
                    if human_action == "approve":
                        actor = "human_cli"
                    elif needs_vp:
                        actor = "vp_agent"
                    else:
                        actor = "system"
                    # LLM text never authorizes pay — only a verified permit does.
                    # Human / VP may clear soft escalation findings via override.
                    permit = get_policy_engine().issue_permit(
                        invoice,
                        actor=actor,
                        open_issues=invoice.issues,
                        allow_soft_override=any(is_soft_escalation(i) for i in invoice.issues),
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
                        "human": human_action == "approve",
                        "actor": actor,
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
                    {
                        "reason": decision.reason,
                        "reflected": decision.reflected,
                        "human": human_action == "reject",
                    },
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
            pay_event = "PaymentRevised" if result.revision else "PaymentSucceeded"
            self.events.emit(
                pay_event,
                correlation_id,
                invoice.invoice_id,
                {
                    "transaction_id": result.transaction_id,
                    "amount": str(result.amount),
                    "vendor": result.vendor,
                    "payment_id": payment_id,
                    "source_stem": source_stem,
                    "revision": result.revision,
                },
                stage=StageName.PAYMENT.value,
            )
            self.metrics.incr_rate(
                StageName.PAYMENT.value, "revised" if result.revision else "paid"
            )
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
