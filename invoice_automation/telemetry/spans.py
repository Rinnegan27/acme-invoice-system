"""Stage spans in OpenTelemetry shape.

Notes
-----
Write JSONL lines to ``spans.jsonl``. Write an OTLP/JSON batch to
``otlp_traces.json``. Set ``GALATIQ_SPAN_CONSOLE=1`` for console output.
Use the OpenTelemetry API when it is installed. A live collector is not
required.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SpanExporter:
    """Write span records to JSONL and OTLP/JSON files."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.otlp_path = self.path.parent / "otlp_traces.json"
        self._otlp_spans: list[dict[str, Any]] = []
        if self.otlp_path.exists():
            try:
                prior = json.loads(self.otlp_path.read_text(encoding="utf-8"))
                self._otlp_spans = list(
                    (((prior.get("resourceSpans") or [{}])[0].get("scopeSpans") or [{}])[0]).get(
                        "spans"
                    )
                    or []
                )
            except (json.JSONDecodeError, TypeError, IndexError, AttributeError):
                self._otlp_spans = []

    def emit(self, span: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(span, separators=(",", ":")) + "\n")
        self._append_otlp(span)
        if os.environ.get("GALATIQ_SPAN_CONSOLE", "").strip() in {"1", "true", "yes"}:
            print(
                f"[span] {span.get('name')} status={span.get('status')} "
                f"attrs={span.get('attributes')}",
                flush=True,
            )

    def _append_otlp(self, span: dict[str, Any]) -> None:
        attrs = [
            {"key": str(k), "value": {"stringValue": str(v)}}
            for k, v in (span.get("attributes") or {}).items()
        ]
        otlp_span = {
            "traceId": span.get("trace_id"),
            "spanId": span.get("span_id"),
            "name": span.get("name"),
            "kind": 1,
            "startTimeUnixNano": str(span.get("start_time_unix_nano")),
            "endTimeUnixNano": str(span.get("end_time_unix_nano")),
            "attributes": attrs,
            "status": {
                "code": 1 if span.get("status") == "OK" else 2,
                "message": "" if span.get("status") == "OK" else "ERROR",
            },
        }
        self._otlp_spans.append(otlp_span)
        batch = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "galatiq-invoice-system"},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "galatiq.spans", "version": "1"},
                            "spans": self._otlp_spans,
                        }
                    ],
                }
            ]
        }
        self.otlp_path.write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")


@contextmanager
def stage_span(
    exporter: SpanExporter | None,
    name: str,
    *,
    correlation_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Record one stage span. Yield a mutable attrs dict."""
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
    # Call OpenTelemetry when the package is installed.
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
        _ = (start, end)
