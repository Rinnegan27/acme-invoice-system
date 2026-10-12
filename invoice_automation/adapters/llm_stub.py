"""Offline deterministic LLM client for CI and demos."""

from __future__ import annotations

from decimal import Decimal

from invoice_automation.adapters.parsers import parse_invoice_text
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import (
    HIGH_VALUE_THRESHOLD,
    ApprovalDecision,
    ExtractionResult,
    Invoice,
)
from invoice_automation.resilience.policies import CircuitBreaker


class OfflineLLM:
    """Deterministic extractor and approver that implements LLMClient.

    Notes
    -----
    This class uses format parsers. It does not call a live model.
    CI stays reproducible. Self-correction retries parse after light
    text cleanup.
    """

    def __init__(self) -> None:
        self.breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_s=10.0)

    def extract(
        self,
        raw_text: str,
        source_path: str,
        deadline_s: float = 30.0,
    ) -> ExtractionResult:
        _ = deadline_s
        self.breaker.before_call()
        try:
            invoice = parse_invoice_text(raw_text, source_path)
            self.breaker.record_success()
            return ExtractionResult(invoice=invoice, raw_confidence=0.9, self_corrected=False)
        except ExtractionError:
            # Self-correction: normalize common OCR/typo noise then retry once.
            normalized = (
                raw_text.replace("INVOCE", "INVOICE")
                .replace("Vndr:", "Vendor:")
                .replace("Inv #:", "Invoice Number:")
                .replace("Inv #", "Invoice Number")
                .replace("Amt:", "Total Amount:")
                .replace("Itms:", "Items:")
                .replace("Due Dt:", "Due Date:")
                .replace("qty ", "qty: ")
            )
            try:
                invoice = parse_invoice_text(normalized, source_path)
                self.breaker.record_success()
                return ExtractionResult(
                    invoice=invoice,
                    raw_confidence=0.7,
                    self_corrected=True,
                    notes="normalized messy text",
                )
            except ExtractionError as exc:
                self.breaker.record_failure()
                raise ExtractionError(str(exc)) from exc

    def approve(self, invoice: Invoice, deadline_s: float = 30.0) -> ApprovalDecision:
        _ = deadline_s
        from invoice_automation.policy.invariants import (
            is_vendor_split_risk,
            partition_soft_escalation_issues,
        )

        other_issues, soft = partition_soft_escalation_issues(invoice.issues)
        if other_issues:
            return ApprovalDecision(
                approved=False,
                reason=f"Rejected due to issues: {', '.join(other_issues)}",
                reflected=invoice.is_high_value or bool(soft),
            )
        if invoice.amount <= 0:
            return ApprovalDecision(
                approved=False,
                reason="Rejected: non-positive amount",
                reflected=True,
            )
        split = [i for i in soft if is_vendor_split_risk(i)]
        if split:
            # Stub VP: hold structuring patterns for manual review (do not auto-pay).
            return ApprovalDecision(
                approved=False,
                reason=(
                    "VP rejected for suspected vendor split / structuring: " + "; ".join(split)
                ),
                reflected=True,
            )
        variants = [i for i in soft if str(i).startswith("sku_variant_review")]
        if variants:
            return ApprovalDecision(
                approved=False,
                reason=(
                    "Rejected: Vendor invoiced for unlisted SKU variant — " + "; ".join(variants)
                ),
                reflected=True,
            )
        typo_reviews = [
            i
            for i in soft
            if not is_vendor_split_risk(i) and not str(i).startswith("sku_variant_review")
        ]
        ambiguous = [i for i in typo_reviews if "→ambiguous:" in str(i)]
        if ambiguous:
            return ApprovalDecision(
                approved=False,
                reason=(
                    "VP rejected ambiguous SKU root (multiple catalog matches): "
                    + "; ".join(ambiguous)
                ),
                reflected=True,
            )
        if typo_reviews:
            # Stub VP: accept clear catalog typo mappings after reflection.
            return ApprovalDecision(
                approved=True,
                reason=("VP approved after SKU typo review: " + "; ".join(typo_reviews)),
                reflected=True,
            )
        if invoice.is_high_value:
            # Reflection loop (stub): scrutinize vendor urgency / fraud signals.
            suspicious = any(
                token in (invoice.vendor + invoice.approval_reason).lower()
                for token in ("fraud", "urgent", "wire")
            ) or any(i.sku.lower() == "fakeitem" for i in invoice.items)
            if suspicious:
                return ApprovalDecision(
                    approved=False,
                    reason=(
                        f"High value ({invoice.amount}) rejected after VP reflection: "
                        "suspicious vendor/item signals"
                    ),
                    reflected=True,
                )
            if invoice.amount > HIGH_VALUE_THRESHOLD * Decimal("5"):
                return ApprovalDecision(
                    approved=False,
                    reason=f"High value ({invoice.amount}) exceeds discretionary limit",
                    reflected=True,
                )
            return ApprovalDecision(
                approved=True,
                reason=f"High value ({invoice.amount}) approved after VP scrutiny",
                reflected=True,
            )
        return ApprovalDecision(
            approved=True,
            reason="Auto-approved under $10k threshold",
            reflected=False,
        )
