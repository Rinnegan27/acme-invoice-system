"""CLI stdout must be a single JSON document (logs on stderr)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from invoice_automation.telemetry.logging_setup import configure_logging

pytestmark = pytest.mark.white_box

ROOT = Path(__file__).resolve().parents[1]


def test_configure_logging_writes_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(logging.INFO)
    logging.getLogger("httpx").info("http request probe")
    logging.getLogger("openai").warning("openai probe")
    captured = capsys.readouterr()
    assert "http request probe" in captured.err
    assert "openai probe" in captured.err
    assert "http request probe" not in captured.out
    assert "openai probe" not in captured.out


def test_stub_cli_stdout_is_single_json_object() -> None:
    env = os.environ.copy()
    env["GALATIQ_PERMIT_SECRET"] = env.get(
        "GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod"
    )
    env["GALATIQ_PROFILE"] = "case"
    proc = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--invoice_path=data/invoices/invoice1.txt",
            "--llm=stub",
            "--profile=case",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    # Strict: entire stdout is one JSON object (optional trailing newline).
    payload = json.loads(proc.stdout)
    assert payload["invoice_id"] == "INV-1001"
    assert payload["status"] == "paid"
    assert "Paid" not in proc.stdout
    # Payment log line (if any) belongs on stderr.
    assert "INFO httpx" not in proc.stdout
