"""AP workbench service: ingest, override, escalate, approve, decline."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_automation.adapters.workbench_store import (
    WorkbenchRecord,
    WorkbenchStore,
)
from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.domain.models import HIGH_VALUE_THRESHOLD, Invoice, LineItem
from invoice_automation.orchestration.pipeline import Pipeline, ReviewDraft


class WorkbenchService:
    """Coordinates pipeline decisions with persistent inbox/VP queue state."""

    def __init__(
        self,
        work_dir: str | Path,
        *,
        use_grok: bool = False,
        profile: str | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.store = WorkbenchStore(self.work_dir / "workbench.db")
        self.pipeline = Pipeline(
            work_dir=self.work_dir / "pipeline",
            use_grok=use_grok,
            profile=profile,
        )

    def reset(self) -> None:
        """Clear all workbench invoices and reseed inventory (demo hygiene)."""
        self.store.clear_all()
        self.pipeline.inventory.reseed()

    def ingest_file(self, path: str | Path, *, actor_role: str = "analyst") -> WorkbenchRecord:
        path = Path(path).resolve()
        draft = self.pipeline.extract_and_validate(path)
        # Upsert is keyed by absolute source_path — re-runs refresh one row, never stack duplicates.
        record = self.store.upsert_from_draft(
            correlation_id=draft.correlation_id,
            source_path=str(path),
            invoice=draft.invoice,
            issues=draft.issues,
            confidence=draft.confidence,
            self_corrected=draft.self_corrected,
            raw_text=draft.raw_text,
            notes=draft.notes,
            hard_blocked=draft.hard_blocked,
        )
        # High-value clear invoices go straight to VP queue status.
        if (
            record.high_value
            and not record.hard_blocked
            and record.status == "pending_review"
            and not record.needs_override
        ):
            record = self.store.update_fields(record.id, status="awaiting_vp", escalated=1)
        self.store.add_event(
            record.correlation_id,
            "Ingested",
            actor_role,
            {"status": record.status, "confidence": record.confidence},
        )
        return record

    def ingest_many(
        self,
        paths: list[Path],
        *,
        actor_role: str = "analyst",
    ) -> tuple[list[WorkbenchRecord], list[str]]:
        ok: list[WorkbenchRecord] = []
        errors: list[str] = []
        for path in paths:
            try:
                ok.append(self.ingest_file(path, actor_role=actor_role))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name}: {exc}")
        return ok, errors

    def list_inbox(self) -> list[WorkbenchRecord]:
        return self.store.list_by_statuses(["pending_review", "needs_override", "awaiting_vp"])

    def list_exceptions(self) -> list[WorkbenchRecord]:
        """True exceptions only — issues, hard blocks, or low-confidence overrides."""
        return [
            r
            for r in self.list_inbox()
            if r.issues or r.needs_override or r.hard_blocked or r.status == "needs_override"
        ]

    def list_vp_queue(self) -> list[WorkbenchRecord]:
        """High-value / escalated desk only — hard blocks stay in Exceptions for analysts."""
        rows = self.store.list_by_statuses(["awaiting_vp", "needs_override", "pending_review"])
        return [r for r in rows if r.status == "awaiting_vp" or r.escalated or r.high_value]

    def list_history(self) -> list[WorkbenchRecord]:
        return self.store.list_by_statuses(["paid", "rejected"])

    def list_all(self) -> list[WorkbenchRecord]:
        return self.store.list_all()

    def get(self, record_id: int) -> WorkbenchRecord | None:
        return self.store.get(record_id)

    def apply_overrides(
        self,
        record_id: int,
        *,
        invoice_id: str,
        vendor: str,
        amount: str,
        due_date: str,
        items_text: str,
        analyst_notes: str,
        actor_role: str = "analyst",
    ) -> WorkbenchRecord:
        record = self.store.get(record_id)
        if record is None:
            raise ValidationError("invoice not found")
        before = {
            "invoice_id": record.invoice_id,
            "vendor": record.vendor,
            "amount": str(record.amount),
            "due_date": record.due_date.isoformat() if record.due_date else "",
            "items": record.items,
        }
        amt = _parse_amount(amount)
        due = _parse_due(due_date)
        items = _parse_items_text(items_text)
        invoice = Invoice(
            invoice_id=invoice_id.strip() or record.invoice_id,
            vendor=vendor.strip() or "Unknown",
            amount=amt,
            due_date=due,
            items=tuple(items),
            source_path=record.source_path,
            correlation_id=record.correlation_id,
        )
        issues = list(self.pipeline.inventory.check_availability(invoice.items))
        if invoice.amount < 0:
            issues.append("negative_amount")
        if not invoice.vendor or invoice.vendor == "Unknown":
            issues.append("missing_vendor")
        hard_blocked = any(
            i.startswith(p)
            for i in issues
            for p in ("unknown_item", "invalid_quantity", "negative_amount")
        )
        if hard_blocked:
            status = "pending_review"
        elif invoice.is_high_value or record.escalated:
            status = "awaiting_vp"
        else:
            status = "pending_review"
        # Manual override clears low-confidence flag for workflow purposes.
        updated = self.store.update_fields(
            record_id,
            invoice_id=invoice.invoice_id,
            vendor=invoice.vendor,
            amount=str(invoice.amount),
            due_date=due.isoformat() if due else None,
            items_json=json.dumps(
                [
                    {
                        "sku": i.sku,
                        "quantity": i.quantity,
                        "unit_price": str(i.unit_price) if i.unit_price is not None else None,
                    }
                    for i in invoice.items
                ]
            ),
            issues_json=json.dumps(issues),
            hard_blocked=1 if hard_blocked else 0,
            high_value=1 if invoice.is_high_value else 0,
            confidence=1.0,
            self_corrected=0,
            status=status,
            analyst_notes=analyst_notes,
            notes="Manual override saved",
        )
        self.store.add_event(
            record.correlation_id,
            "FieldsOverridden",
            actor_role,
            {
                "before": before,
                "after": {
                    "invoice_id": updated.invoice_id,
                    "vendor": updated.vendor,
                    "amount": str(updated.amount),
                    "issues": updated.issues,
                },
            },
        )
        return updated

    def escalate(
        self, record_id: int, *, actor_role: str = "analyst", note: str = ""
    ) -> WorkbenchRecord:
        record = self._require(record_id)
        updated = self.store.update_fields(
            record_id,
            status="awaiting_vp",
            escalated=1,
            analyst_notes=note or record.analyst_notes,
        )
        self.store.add_event(
            record.correlation_id,
            "EscalatedToVP",
            actor_role,
            {"note": note},
        )
        return updated

    def return_to_analyst(
        self, record_id: int, *, actor_role: str = "vp", note: str = ""
    ) -> WorkbenchRecord:
        record = self._require(record_id)
        status = "needs_override" if record.needs_override else "pending_review"
        updated = self.store.update_fields(
            record_id,
            status=status,
            escalated=0,
            notes=note or "Returned to analyst",
        )
        self.store.add_event(
            record.correlation_id,
            "ReturnedToAnalyst",
            actor_role,
            {"note": note},
        )
        return updated

    def auto_complete(self, record_id: int) -> WorkbenchRecord:
        """Advance one invoice through policy auto-path (CLI/UI sim spine).

        1. Hard-blocked → reject (never pay)
        2. Soft issues + not high-value → reject
        3. High-value → approval agent reflection via pipeline.auto_approve
        4. Clean ≤$10k → analyst pay
        """
        record = self._require(record_id)
        if record.hard_blocked:
            return self.decline(
                record_id,
                actor_role="system",
                reason=f"Auto-rejected hard block: {', '.join(record.issues)}",
            )
        if record.issues and not record.high_value:
            return self.decline(
                record_id,
                actor_role="system",
                reason=f"Auto-rejected validation issues: {', '.join(record.issues)}",
            )
        if record.high_value or record.amount > HIGH_VALUE_THRESHOLD:
            draft = self._to_draft(record)
            result = self.pipeline.auto_approve(draft)
            status = result.status
            if status == "paid":
                # Sync workbench after pipeline paid under a PaymentPermit.
                updated = self.store.update_fields(
                    record.id,
                    status="paid",
                    notes=result.approval_reason or "VP agent approved & paid",
                )
                self.store.add_event(
                    record.correlation_id,
                    "Paid",
                    "vp_agent",
                    {"reason": result.approval_reason, "reflected": True, "auto": True},
                )
                return updated
            updated = self.store.update_fields(
                record.id,
                status="rejected",
                notes=result.approval_reason or f"Auto-rejected: {', '.join(result.issues)}",
            )
            self.store.add_event(
                record.correlation_id,
                "Declined",
                "vp_agent",
                {
                    "reason": result.approval_reason,
                    "issues": list(result.issues),
                    "auto": True,
                },
            )
            return updated
        return self.analyst_submit_pay(record_id)

    def analyst_submit_pay(self, record_id: int, *, actor: str = "analyst") -> WorkbenchRecord:
        """Analyst may pay only clear, non-high-value, non-blocked invoices."""
        record = self._require(record_id)
        if record.hard_blocked:
            raise ValidationError("Cannot pay while hard validation failures remain")
        if record.high_value or record.amount > HIGH_VALUE_THRESHOLD:
            raise ValidationError("High-value invoices must be approved by a VP")
        if record.needs_override and record.status == "needs_override":
            raise ValidationError("Save overrides for low-confidence extracts before paying")
        if record.issues:
            raise ValidationError("Resolve validation findings or escalate to VP")
        return self._pay(
            record,
            actor_role=actor,
            reason="Analyst approved & paid",
            allow_soft_override=False,
        )

    def vp_approve_pay(
        self,
        record_id: int,
        *,
        note: str = "",
        policy_override: bool = False,
        actor: str = "vp",
    ) -> WorkbenchRecord:
        record = self._require(record_id)
        if record.hard_blocked:
            raise ValidationError("Cannot pay while hard validation failures remain")
        if record.issues and not policy_override:
            raise ValidationError("Cannot pay with open findings unless policy_override=True")
        if record.issues and policy_override:
            self.store.add_event(
                record.correlation_id,
                "PolicyOverride",
                actor,
                {"issues": list(record.issues), "note": note},
            )
        return self._pay(
            record,
            actor_role=actor,
            reason=note or "VP approved & paid",
            allow_soft_override=policy_override,
        )

    def vp_approve_all(self, *, note: str = "", actor: str = "vp") -> tuple[int, int, list[str]]:
        """Approve & pay clean VP-desk invoices only (no policy override).

        Returns
        -------
        tuple
            (approved_count, skipped_count, error_messages)
        """
        approved = 0
        skipped = 0
        errors: list[str] = []
        for record in list(self.list_vp_queue()):
            if record.hard_blocked or record.issues:
                skipped += 1
                continue
            try:
                self.vp_approve_pay(
                    record.id,
                    note=note or "VP bulk approve & pay",
                    policy_override=False,
                    actor=actor,
                )
                approved += 1
            except ValidationError as exc:
                errors.append(f"{record.invoice_id}: {exc}")
                skipped += 1
        return approved, skipped, errors

    def vp_reject_all(self, *, reason: str = "", actor: str = "vp") -> tuple[int, list[str]]:
        """Reject every invoice currently on the VP desk."""
        rejected = 0
        errors: list[str] = []
        reason = reason or "VP bulk reject"
        for record in list(self.list_vp_queue()):
            try:
                self.decline(record.id, actor_role=actor, reason=reason)
                rejected += 1
            except ValidationError as exc:
                errors.append(f"{record.invoice_id}: {exc}")
        return rejected, errors

    def decline(
        self,
        record_id: int,
        *,
        actor_role: str,
        reason: str,
    ) -> WorkbenchRecord:
        record = self._require(record_id)
        draft = self._to_draft(record)
        self.pipeline.human_reject(draft, reason=reason)
        updated = self.store.update_fields(record_id, status="rejected", notes=reason)
        self.store.add_event(
            record.correlation_id,
            "Declined",
            actor_role,
            {"reason": reason},
        )
        return updated

    def _pay(
        self,
        record: WorkbenchRecord,
        *,
        actor_role: str,
        reason: str,
        allow_soft_override: bool = False,
    ) -> WorkbenchRecord:
        """Pay only through PolicyEngine PaymentPermit — never clears findings."""
        draft = self._to_draft(record)
        draft = ReviewDraft(
            correlation_id=draft.correlation_id,
            source_path=draft.source_path,
            raw_text=draft.raw_text,
            invoice=draft.invoice.with_updates(approval_reason=reason),
            issues=draft.issues,
            confidence=draft.confidence,
            self_corrected=draft.self_corrected,
            notes=reason,
        )
        result = self.pipeline.human_approve(
            draft,
            actor=actor_role,
            allow_soft_override=allow_soft_override,
        )
        if result.status != "paid":
            raise ValidationError(f"Payment did not complete: {result.status}")
        updated = self.store.update_fields(record.id, status="paid", notes=reason)
        self.store.add_event(
            record.correlation_id,
            "Paid",
            actor_role,
            {"reason": reason, "permit_fenced": True},
        )
        return updated

    def _to_draft(self, record: WorkbenchRecord) -> ReviewDraft:
        invoice = record.to_invoice()
        return ReviewDraft(
            correlation_id=record.correlation_id,
            source_path=record.source_path,
            raw_text=record.raw_text,
            invoice=invoice,
            issues=tuple(record.issues),
            confidence=record.confidence,
            self_corrected=record.self_corrected,
            notes=record.notes,
        )

    def list_reconcile(self) -> list[dict]:
        """Open pay/stock RECONCILE intents from the pipeline saga."""
        return self.pipeline.saga.list_reconcile_intents()

    def retry_reconcile_stock(self, invoice_id: str, *, actor_role: str = "ops") -> dict:
        """Retry stock decrement for a RECONCILE intent."""
        from invoice_automation.domain.exceptions import PaymentError

        try:
            result = self.pipeline.saga.retry_stock_decrement(invoice_id)
        except PaymentError as exc:
            raise ValidationError(str(exc)) from exc
        self.pipeline.outbox.flush()
        return {
            "invoice_id": invoice_id,
            "status": result.status,
            "transaction_id": result.transaction_id,
            "actor": actor_role,
        }

    def acknowledge_reconcile(
        self, invoice_id: str, *, note: str = "", actor_role: str = "ops"
    ) -> dict:
        """Ack a RECONCILE intent without retrying stock."""
        from invoice_automation.domain.exceptions import PaymentError

        try:
            self.pipeline.saga.acknowledge_reconcile(invoice_id, note=note)
        except PaymentError as exc:
            raise ValidationError(str(exc)) from exc
        self.pipeline.outbox.flush()
        return {"invoice_id": invoice_id, "status": "acked", "note": note, "actor": actor_role}

    def _require(self, record_id: int) -> WorkbenchRecord:
        record = self.store.get(record_id)
        if record is None:
            raise ValidationError("invoice not found")
        return record


def _parse_amount(value: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("invalid amount") from exc


def _parse_due(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y/%m/%d").date()
        except ValueError as exc:
            raise ValidationError("due date must be YYYY-MM-DD") from exc


def _parse_items_text(text: str) -> list[LineItem]:
    """Parse lines as: SKU,qty[,unit_price]."""
    items: list[LineItem] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            raise ValidationError(f"bad line item: {line}")
        sku = parts[0]
        qty = int(parts[1])
        price = Decimal(parts[2]) if len(parts) > 2 and parts[2] else None
        items.append(LineItem(sku=sku, quantity=qty, unit_price=price))
    if not items:
        raise ValidationError("at least one line item is required")
    return items
