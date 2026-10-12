"""Structured logging configuration.

Notes
-----
All log handlers write to **stderr** so CLI/sim ``stdout`` stays a single JSON
document (including live Grok / httpx traffic).
"""

from __future__ import annotations

import logging
import sys

# Third-party loggers that otherwise attach stdout handlers.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "urllib3",
    "httpcore.connection",
    "httpcore.http11",
)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root and noisy library loggers to emit on stderr only.

    Parameters
    ----------
    level : int
        Logging level.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s %(message)s"
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in _NOISY_LOGGERS:
        lib = logging.getLogger(name)
        lib.handlers.clear()
        lib.propagate = True
        lib.setLevel(level)


class CorrelationFilter(logging.Filter):
    """Ensure correlation_id exists on every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True
