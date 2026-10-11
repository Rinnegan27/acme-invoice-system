from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class EventLog:
    def __init__(self, path: str = "events.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        correlation_id: str,
        invoice_id: str,
        payload: Optional[Dict[str, Any]] = None,
        stage: Optional[str] = None,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "correlation_id": correlation_id,
            "invoice_id": invoice_id,
            "stage": stage,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
