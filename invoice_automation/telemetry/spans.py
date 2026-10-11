"""Lightweight OpenTelemetry-shaped stage spans.

Notes
-----
Writes JSON span lines to ``spans.jsonl`` under the runtime work dir.
Uses the OpenTelemetry API when installed; otherwise emits compatible JSON.
Does not require a live OTLP collector.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SpanExporter:
    """Append OTel-like span records to a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, span: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(span, separators=(",", ":")) + "\n")


@contextmanager
def stage_span(
    exporter: SpanExporter | None,
    name: str,
    *,
    correlation_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Record a stage span. Always yields a mutable attrs dict."""
    start = time.time()
    attrs: dict[str, Any] = dict(attributes or {})
    if correlation_id:
        attrs["correlation_id"] = correlation_id
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    status = "OK"
    try:
        yield attrs
    except Exception as exc:  # noqa: BLE001 - span status then re-raise
        status = "ERROR"
        attrs["error.type"] = type(exc).__name__
        attrs["error.message"] = str(exc)
        raise
    finally:
        if exporter is not None:
            end = time.time()
            exporter.emit(
                {
                    "name": name,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "start_time_unix_nano": int(start * 1e9),
                    "end_time_unix_nano": int(end * 1e9),
                    "status": status,
                    "attributes": attrs,
                    "instrumentation": "galatiq.spans",
                }
            )
            _try_otel_record(name, start, end, status, attrs)


def _try_otel_record(
    name: str,
    start: float,
    end: float,
    status: str,
    attrs: dict[str, Any],
) -> None:
    """Best-effort OpenTelemetry API hook when the package is present."""
    try:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode
    except ImportError:
        return
    tracer = trace.get_tracer("galatiq.invoice_automation")
    with tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            span.set_attribute(str(key), str(value))
        span.set_status(Status(StatusCode.OK if status == "OK" else StatusCode.ERROR))
        # Duration is implicit; keep API call side-effect free beyond attributes.
        _ = (start, end)
