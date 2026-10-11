"""CLI summary helpers and llm default resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.adapters.llm_grok import GrokAuthError
from invoice_automation.main import (
    build_parser,
    ensure_llm_ready,
    full_result,
    resolve_llm,
    summarize_result,
)
from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.white_box

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def test_summarize_result_is_compact(tmp_path: Path) -> None:
    pipe = Pipeline(work_dir=tmp_path / "cli", use_grok=False)
    result = pipe.process_file(DATA / "invoice_1001.txt")
    summary = summarize_result(result)
    assert set(summary) == {
        "invoice_id",
        "status",
        "vendor",
        "amount",
        "issues",
        "approval_reason",
        "llm_tokens_total",
    }
    assert "events" not in summary
    assert summary["status"] == "paid"
    assert summary["vendor"] == "Widgets Inc."

    verbose = full_result(result)
    assert "events" in verbose
    assert "metrics" in verbose


def test_llm_default_is_grok() -> None:
    parser = build_parser()
    args = parser.parse_args(["--invoice_path", "data/invoices/invoice1.txt"])
    assert args.llm == "grok"
    assert args.verbose is False


def test_resolve_llm_stub_passthrough() -> None:
    assert resolve_llm("stub") == "stub"


def test_resolve_llm_grok_when_key_present(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-live-test-key-not-placeholder")
    assert resolve_llm("grok") == "grok"


def test_resolve_llm_prompts_offline_when_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("invoice_automation.main.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert resolve_llm("grok") == "stub"


def test_resolve_llm_noninteractive_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr("invoice_automation.main.sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit, match="XAI_API_KEY"):
        resolve_llm("grok")


def test_ensure_llm_ready_falls_back_offline_on_bad_key(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-definitely-wrong-key-0123456789")
    monkeypatch.setattr("invoice_automation.main.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "2")

    def _boom(self) -> None:  # noqa: ANN001
        raise GrokAuthError("XAI_API_KEY was rejected by xAI (incorrect or revoked).")

    monkeypatch.setattr(
        "invoice_automation.main.GrokLLM.verify_credentials",
        _boom,
    )
    assert ensure_llm_ready("grok") == "stub"


def test_ensure_llm_ready_noninteractive_bad_key(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-definitely-wrong-key-0123456789")
    monkeypatch.setattr("invoice_automation.main.sys.stdin.isatty", lambda: False)

    def _boom(self) -> None:  # noqa: ANN001
        raise GrokAuthError("XAI_API_KEY was rejected by xAI (incorrect or revoked).")

    monkeypatch.setattr(
        "invoice_automation.main.GrokLLM.verify_credentials",
        _boom,
    )
    with pytest.raises(SystemExit, match="rejected"):
        ensure_llm_ready("grok")
