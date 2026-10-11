"""Append-only JSONL event sink."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlEventLog:
    """Structured JSONL event log implementing EventSink."""

    def __init__(self, path: str | Path = "events.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        correlation_id: str,
        invoice_id: str,
        payload: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "correlation_id": correlation_id,
            "invoice_id": invoice_id,
            "stage": stage,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events
