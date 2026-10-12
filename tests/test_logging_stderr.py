"""Logging setup keeps machine stdout clean."""

from __future__ import annotations

import logging

import pytest

from invoice_automation.telemetry.logging_setup import configure_logging

pytestmark = pytest.mark.white_box


def test_reconfigure_replaces_stdout_handlers(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(logging.StreamHandler())  # defaults to sys.stderr in some envs
    # Force a stdout handler to prove we strip it.
    import sys

    bad = logging.StreamHandler(sys.stdout)
    root.addHandler(bad)
    configure_logging(logging.INFO)
    logging.getLogger().info("after reconfigure")
    captured = capsys.readouterr()
    assert "after reconfigure" in captured.err
    assert "after reconfigure" not in captured.out
    assert all(getattr(h, "stream", None) is sys.stderr for h in root.handlers)
