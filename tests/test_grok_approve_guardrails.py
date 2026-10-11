"""Deterministic Grok approve guardrails (no live API)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from invoice_automation.adapters.llm_grok import APPROVE_SCHEMA, GrokLLM
from invoice_automation.domain.models import Invoice, InvoiceStatus, LineItem

pytestmark = pytest.mark.white_box


def _invoice(**kwargs: object) -> Invoice:
    base = dict(
        invoice_id="INV-T",
        vendor="Acme",
        amount=Decimal("5000"),
        due_date=None,
        items=(LineItem("WidgetA", 1, Decimal("100")),),
        source_path="t.txt",
        status=InvoiceStatus.VALIDATED,
        issues=(),
        correlation_id="c1",
    )
    base.update(kwargs)
    return Invoice(**base)  # type: ignore[arg-type]


def test_approve_schema_is_strict_json_schema() -> None:
    assert APPROVE_SCHEMA["type"] == "json_schema"
    assert APPROVE_SCHEMA["json_schema"]["strict"] is True


def test_non_hv_empty_issues_approves_without_model_call() -> None:
    client = MagicMock()
    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder")
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
    decision = llm.approve(_invoice())
    assert decision.approved is True
    assert "policy gate" in decision.reason.lower() or "validation" in decision.reason.lower()
    client.chat.completions.create.assert_not_called()


def test_open_issues_always_reject() -> None:
    client = MagicMock()
    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder")
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
    decision = llm.approve(_invoice(issues=("insufficient_stock:GadgetX",)))
    assert decision.approved is False
    client.chat.completions.create.assert_not_called()


def test_hv_fakeitem_rejected_without_model() -> None:
    client = MagicMock()
    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder")
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
    decision = llm.approve(
        _invoice(
            amount=Decimal("12500"),
            items=(LineItem("FakeItem", 1, Decimal("1")),),
        )
    )
    assert decision.approved is False
    assert "FakeItem" in decision.reason
    client.chat.completions.create.assert_not_called()


def test_hv_deterministic_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setenv("GALATIQ_HV_DETERMINISTIC", "1")
    payload = {"approved": True, "reason": "ok", "reflected": True}

    class _Usage:
        total_tokens = 1

    class _Msg:
        content = json.dumps(payload)

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    client = MagicMock()
    client.chat.completions.create.return_value = _Resp()
    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder")
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
    decision = llm.approve(_invoice(amount=Decimal("12500")))
    assert decision.approved is True
    assert client.chat.completions.create.call_count == 1
    assert llm.last_approve_audit is not None
    assert llm.last_approve_audit["mode"] == "hv_deterministic"
