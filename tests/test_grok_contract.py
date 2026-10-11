"""Grok client contract tests (offline fixtures + optional live mark)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from invoice_automation.adapters.llm_grok import (
    GrokAuthError,
    GrokLLM,
    is_grok_auth_error,
)
from invoice_automation.case_brief import is_live_xai_key
from invoice_automation.telemetry.metrics import InMemoryMetrics

pytestmark = pytest.mark.white_box

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "grok"


def test_grok_extract_uses_fixture_json() -> None:
    payload = json.loads((FIXTURES / "extract_ok.json").read_text(encoding="utf-8"))
    metrics = InMemoryMetrics()

    class _Usage:
        total_tokens = 42

    class _Msg:
        content = json.dumps(payload)

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    client = MagicMock()
    client.chat.completions.create.return_value = _Resp()

    with patch("openai.OpenAI", return_value=client):
        llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder", metrics=metrics)
        # Avoid real network path inside _client by patching _client
        llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
        result = llm.extract("ignored raw", "invoice_fixture.txt", deadline_s=5.0)

    assert result.invoice.invoice_id == "INV-FIXTURE"
    assert result.invoice.vendor == "Widgets Inc."
    assert len(result.invoice.items) == 2
    assert metrics.snapshot()["llm_tokens_total"] == 42
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs.get("response_format") is not None


def test_grok_parser_fallback_metric() -> None:
    metrics = InMemoryMetrics()
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")

    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder", metrics=metrics)
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]

    raw = Path(__file__).resolve().parents[1] / "data" / "invoices" / "invoice_1001.txt"
    result = llm.extract(raw.read_text(encoding="utf-8"), str(raw), deadline_s=5.0)
    assert result.invoice.invoice_id == "INV-1001"
    assert result.self_corrected is True
    assert metrics.snapshot()["rates"].get("extract:parser_fallback") == 1


def test_is_grok_auth_error_detects_status_and_message() -> None:
    class _Fake401(Exception):
        status_code = 401

    assert is_grok_auth_error(_Fake401("nope"))
    assert is_grok_auth_error(RuntimeError("Incorrect API key provided: xai-***"))
    assert not is_grok_auth_error(RuntimeError("timeout talking to upstream"))


def test_grok_extract_does_not_fallback_on_auth_error() -> None:
    metrics = InMemoryMetrics()
    client = MagicMock()

    class _AuthBoom(Exception):
        status_code = 401

    client.chat.completions.create.side_effect = _AuthBoom("Incorrect API key provided")

    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder", metrics=metrics)
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]

    raw = Path(__file__).resolve().parents[1] / "data" / "invoices" / "invoice_1001.txt"
    with pytest.raises(GrokAuthError, match="rejected"):
        llm.extract(raw.read_text(encoding="utf-8"), str(raw), deadline_s=5.0)
    assert metrics.snapshot()["rates"].get("extract:parser_fallback") is None


def test_verify_credentials_raises_on_auth_error() -> None:
    client = MagicMock()

    class _AuthBoom(Exception):
        status_code = 401

    client.chat.completions.create.side_effect = _AuthBoom("Incorrect API key provided")
    llm = GrokLLM(api_key="xai-test-fixture-key-not-placeholder")
    llm._client = lambda timeout_s=None: client  # type: ignore[method-assign]
    with pytest.raises(GrokAuthError, match="rejected"):
        llm.verify_credentials()


@pytest.mark.live_grok
def test_live_grok_smoke_optional() -> None:
    import os

    if not is_live_xai_key(os.getenv("XAI_API_KEY")):
        pytest.skip("live XAI_API_KEY not configured")
    llm = GrokLLM()
    raw = (
        Path(__file__).resolve().parents[1] / "data" / "invoices" / "invoice_1001.txt"
    ).read_text(encoding="utf-8")
    result = llm.extract(raw, "invoice_1001.txt", deadline_s=45.0)
    assert result.invoice.vendor
    assert result.invoice.items
