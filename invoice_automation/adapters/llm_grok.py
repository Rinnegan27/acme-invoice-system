"""Live Grok LLM client through the OpenAI-compatible xAI API.

Notes
-----
Bad API keys raise :class:`GrokAuthError`. After an auth failure, extract
must not fall back to the offline parser.

The case README shows ``from xai import Grok``. This module uses
``openai.OpenAI`` with base URL ``https://api.x.ai/v1`` instead.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from invoice_automation.adapters.parsers import normalize_invoice_id, parse_invoice_text
from invoice_automation.case_brief import GROK_MODEL, is_live_xai_key
from invoice_automation.domain.exceptions import ExtractionError
from invoice_automation.domain.models import (
    ApprovalDecision,
    ExtractionResult,
    Invoice,
    InvoiceStatus,
    LineItem,
)
from invoice_automation.resilience.policies import CircuitBreaker, with_retry


class _MetricsProto(Protocol):
    def incr_tokens(self, n: int) -> None: ...

    def incr_rate(self, stage: str, outcome: str) -> None: ...


class _LineItemModel(BaseModel):
    sku: str
    quantity: int
    unit_price: Decimal | None = None


class _ExtractModel(BaseModel):
    invoice_id: str
    vendor: str
    amount: Decimal
    due_date: str | None = None
    items: list[_LineItemModel] = Field(default_factory=list)
    notes: str = ""

    @field_validator("vendor")
    @classmethod
    def vendor_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("vendor required")
        return value


class _ApproveModel(BaseModel):
    approved: bool
    reason: str
    reflected: bool = True


# Pinned prompt versions for eval / change control (bump when text changes).
EXTRACT_PROMPT_VERSION = "extract-v2"
APPROVE_PROMPT_VERSION = "approve-v2"

EXTRACT_SYSTEM = """You extract structured invoice data for Acme Corp.
Return ONLY valid JSON with keys:
invoice_id (string), vendor (string), amount (number), due_date (YYYY-MM-DD or null),
items (array of {sku, quantity, unit_price}), notes (string).
Prefer invoice_id in the form INV-1001 (include the INV- prefix).
Do not invent SKUs that are not present. Quantity must be an integer.
If data is missing, use best effort and mention gaps in notes."""

APPROVE_SYSTEM = """You are a VP reviewing invoices for Acme Corp.
Return ONLY JSON: {"approved": bool, "reason": string, "reflected": true}.
Rules:
- If issues is non-empty, reject.
- If issues is empty and high_value is false, approve (validation already passed).
- If high_value is true, scrutinize fraud, FakeItem, urgency pressure, and stock risk.
Do not invent new validation issues that validation did not raise."""


class GrokAuthError(RuntimeError):
    """Raised when xAI rejects the configured API key."""


def is_grok_auth_error(exc: BaseException) -> bool:
    """Classify provider errors that mean an invalid or revoked API key.

    Parameters
    ----------
    exc : BaseException
        Exception from the OpenAI-compatible client.

    Returns
    -------
    bool
        True when the error is an auth rejection.
    """
    try:
        from openai import AuthenticationError

        if isinstance(exc, AuthenticationError):
            return True
    except ImportError:
        pass

    status = getattr(exc, "status_code", None)
    if status in {401, 403}:
        return True

    text = str(exc).lower()
    markers = (
        "incorrect api key",
        "invalid_api_key",
        "invalid api key",
        "api key not found",
        "wrong api key",
    )
    return any(m in text for m in markers)


EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "invoice_extract",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "invoice_id": {"type": "string"},
                "vendor": {"type": "string"},
                "amount": {"type": "number"},
                "due_date": {"type": ["string", "null"]},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "sku": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "unit_price": {"type": ["number", "null"]},
                        },
                        "required": ["sku", "quantity", "unit_price"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["invoice_id", "vendor", "amount", "due_date", "items", "notes"],
        },
    },
}

APPROVE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "invoice_approve",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "approved": {"type": "boolean"},
                "reason": {"type": "string"},
                "reflected": {"type": "boolean"},
            },
            "required": ["approved", "reason", "reflected"],
        },
    },
}


class GrokLLM:
    """Live Grok client with schema validation and self-correction.

    Parameters
    ----------
    api_key : str or None
        xAI API key. Default reads ``XAI_API_KEY``.
    model : str or None
        Model name. Default reads ``XAI_MODEL`` or the case-brief model.
    timeout_s : float
        Per-request timeout in seconds.
    metrics : object or None
        Optional metrics collector with ``incr_tokens`` / ``incr_rate``.

    Raises
    ------
    RuntimeError
        If the key is missing or a placeholder.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 45.0,
        metrics: _MetricsProto | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("XAI_API_KEY", "")
        self.model = model or os.getenv("XAI_MODEL", GROK_MODEL)
        self.timeout_s = timeout_s
        self.metrics = metrics
        # Tighter breaker: open faster on provider faults; longer cool-down.
        self.breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=90.0)
        self.extract_prompt_version = EXTRACT_PROMPT_VERSION
        self.approve_prompt_version = APPROVE_PROMPT_VERSION
        self.last_approve_audit: dict[str, Any] | None = None
        if not is_live_xai_key(self.api_key):
            raise RuntimeError(
                "XAI_API_KEY is required for GrokLLM "
                '(case placeholder is api_key="your_key" — set a real key in .env)'
            )

    @staticmethod
    def _hv_deterministic() -> bool:
        return os.environ.get("GALATIQ_HV_DETERMINISTIC", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    def _client(self, timeout_s: float | None = None) -> Any:
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url="https://api.x.ai/v1",
            timeout=timeout_s if timeout_s is not None else self.timeout_s,
        )

    def _record_usage(self, resp: Any) -> None:
        if self.metrics is None:
            return
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        total = getattr(usage, "total_tokens", None)
        if total is None:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            total = prompt + completion
        self.metrics.incr_tokens(int(total or 0))

    def verify_credentials(self) -> None:
        """Probe xAI so incorrect keys fail before invoice processing.

        Raises
        ------
        GrokAuthError
            If xAI rejects the configured key.
        """
        client = self._client(timeout_s=min(self.timeout_s, 20.0))
        try:
            client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001 - classify auth vs other probe errors
            if is_grok_auth_error(exc):
                raise GrokAuthError(
                    "XAI_API_KEY was rejected by xAI (incorrect or revoked). "
                    "Update the key in .env, or use --llm=stub for offline."
                ) from exc
            # Network/model glitches: key shape was accepted enough to get past auth.
            return

    def _raise_if_auth(self, exc: BaseException) -> None:
        if is_grok_auth_error(exc):
            raise GrokAuthError(
                "XAI_API_KEY was rejected by xAI (incorrect or revoked). "
                "Update the key in .env, or use --llm=stub for offline."
            ) from exc

    def _chat_json(
        self,
        system: str,
        user: str,
        *,
        timeout_s: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.breaker.before_call()
        fmt = response_format or {"type": "json_object"}

        def _call() -> dict[str, Any]:
            client = self._client(timeout_s)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": fmt,
            }
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc:
                self._raise_if_auth(exc)
                # Some models reject json_schema; retry with json_object / plain.
                kwargs["response_format"] = {"type": "json_object"}
                try:
                    resp = client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    self._raise_if_auth(exc2)
                    kwargs.pop("response_format", None)
                    try:
                        resp = client.chat.completions.create(**kwargs)
                    except Exception as exc3:
                        self._raise_if_auth(exc3)
                        raise
            self._record_usage(resp)
            content = resp.choices[0].message.content or ""
            return _parse_json_content(content)

        try:
            data = with_retry(
                _call,
                attempts=2,
                base_delay_s=0.2,
                no_retry_on=(GrokAuthError,),
            )
            self.breaker.record_success()
            return data
        except GrokAuthError:
            raise
        except Exception:
            self.breaker.record_failure()
            raise

    def extract(
        self,
        raw_text: str,
        source_path: str,
        deadline_s: float = 30.0,
    ) -> ExtractionResult:
        last_error = ""
        for attempt in range(3):
            critique = f"\nPrevious error: {last_error}" if last_error else ""
            user = (
                f"Source: {source_path}\n"
                f"Attempt: {attempt + 1}\n"
                f"Invoice document:\n```\n{raw_text[:12000]}\n```"
                f"{critique}"
            )
            try:
                data = self._chat_json(
                    EXTRACT_SYSTEM,
                    user,
                    timeout_s=deadline_s,
                    response_format=EXTRACT_SCHEMA,
                )
                model = _ExtractModel.model_validate(data)
                if not model.items:
                    raise ExtractionError("model returned no items")
                invoice = Invoice(
                    invoice_id=normalize_invoice_id(
                        model.invoice_id, fallback=Path(source_path).stem
                    ),
                    vendor=model.vendor,
                    amount=model.amount,
                    due_date=_parse_grok_due_date(model.due_date),
                    items=tuple(
                        LineItem(
                            sku=i.sku,
                            quantity=i.quantity,
                            unit_price=i.unit_price,
                        )
                        for i in model.items
                    ),
                    source_path=source_path,
                    status=InvoiceStatus.EXTRACTED,
                )
                return ExtractionResult(
                    invoice=invoice,
                    raw_confidence=0.85,
                    self_corrected=attempt > 0,
                    notes=model.notes,
                )
            except GrokAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 - model/network/schema failures → retry/fallback
                last_error = str(exc)

        if self.metrics is not None:
            self.metrics.incr_rate("extract", "parser_fallback")
        try:
            invoice = parse_invoice_text(raw_text, source_path)
            return ExtractionResult(
                invoice=invoice,
                raw_confidence=0.5,
                self_corrected=True,
                notes=f"fallback parser after grok errors: {last_error}",
            )
        except ExtractionError as exc:
            raise ExtractionError(f"grok extract failed: {last_error}") from exc

    def approve(self, invoice: Invoice, deadline_s: float = 30.0) -> ApprovalDecision:
        """Approve or reject with schema-validated JSON and policy guardrails.

        Notes
        -----
        Guardrails (deterministic; run before/after the model):
        1. Non-empty ``issues`` → always reject (validation already failed).
        2. Empty ``issues`` and not high-value → always approve (matches stub /
           case scenario matrix; model cannot invent new rejects).
        3. High-value with FakeItem → always reject.
        4. Other high-value invoices → Grok VP reflection with ``APPROVE_SCHEMA``.
        """
        self.last_approve_audit = None
        # Guardrail 1: validation findings always win.
        if invoice.issues:
            return ApprovalDecision(
                approved=False,
                reason=f"Rejected due to issues: {', '.join(invoice.issues)}",
                reflected=False,
            )
        # Guardrail 2: clean non-HV invoices follow the case matrix / stub path.
        if not invoice.is_high_value:
            if invoice.amount <= 0:
                return ApprovalDecision(
                    approved=False,
                    reason="Rejected: non-positive amount",
                    reflected=True,
                )
            return ApprovalDecision(
                approved=True,
                reason="Auto-approved under $10k after validation (policy gate)",
                reflected=False,
            )
        # Guardrail 3: FakeItem never clears high-value scrutiny.
        if any(i.sku.lower() == "fakeitem" for i in invoice.items):
            return ApprovalDecision(
                approved=False,
                reason=f"High value ({invoice.amount}) rejected: FakeItem present",
                reflected=True,
            )

        payload = {
            "invoice_id": invoice.invoice_id,
            "vendor": invoice.vendor,
            "amount": str(invoice.amount),
            "items": [
                {"sku": i.sku, "quantity": i.quantity, "unit_price": str(i.unit_price)}
                for i in invoice.items
            ],
            "issues": list(invoice.issues),
            "high_value": True,
        }
        user_prompt = json.dumps(payload)
        data = self._chat_json(
            APPROVE_SYSTEM,
            user_prompt,
            timeout_s=deadline_s,
            response_format=APPROVE_SCHEMA,
        )
        decision = _ApproveModel.model_validate(data)
        critique_user = (
            "Critique this VP decision. Look for fraud, FakeItem, urgency pressure, "
            "stock issues. Return revised JSON decision.\n"
            f"Invoice: {json.dumps(payload)}\n"
            f"Initial decision: {decision.model_dump_json()}"
        )
        # Deterministic mode: one temperature-0 call; record prompt + JSON for audit.
        if self._hv_deterministic():
            self.last_approve_audit = {
                "mode": "hv_deterministic",
                "temperature": 0,
                "system": APPROVE_SYSTEM,
                "user": user_prompt,
                "response": data,
                "prompt_version": self.approve_prompt_version,
            }
            return ApprovalDecision(
                approved=decision.approved,
                reason=decision.reason,
                reflected=True,
            )
        data2 = self._chat_json(
            APPROVE_SYSTEM,
            critique_user,
            timeout_s=deadline_s,
            response_format=APPROVE_SCHEMA,
        )
        decision = _ApproveModel.model_validate(data2)
        self.last_approve_audit = {
            "mode": "hv_critique",
            "temperature": 0,
            "system": APPROVE_SYSTEM,
            "user": critique_user,
            "initial_response": data,
            "response": data2,
            "prompt_version": self.approve_prompt_version,
        }
        return ApprovalDecision(
            approved=decision.approved,
            reason=decision.reason,
            reflected=True,
        )


def _parse_grok_due_date(value: str | None) -> date | None:
    """Parse Grok due_date strings. Invalid values become None (not a hard fail)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y/%m/%d").date()
        except ValueError:
            return None


def _parse_json_content(content: str) -> dict[str, Any]:
    content = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence:
        content = fence.group(1)
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
    return json.loads(content)
