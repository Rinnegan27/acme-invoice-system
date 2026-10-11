"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger for structured console output.

    Parameters
    ----------
    level : int
        Logging level.
    """
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s %(message)s"
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


class CorrelationFilter(logging.Filter):
    """Ensure correlation_id exists on every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True
