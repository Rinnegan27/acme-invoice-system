"""In-memory RED metrics collector with optional disk snapshot."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


class InMemoryMetrics:
    """Process-local RED + outcome metrics.

    Notes
    -----
    Suitable for local prototype and tests. Snapshot can be persisted to work_dir.
    """

    def __init__(self) -> None:
        self._latency_sum: dict[str, float] = defaultdict(float)
        self._latency_count: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)
        self._rates: dict[str, int] = defaultdict(int)
        self._llm_tokens: int = 0

    def observe_latency(self, stage: str, seconds: float) -> None:
        self._latency_sum[stage] += seconds
        self._latency_count[stage] += 1

    def incr_error(self, stage: str, error_class: str) -> None:
        self._errors[f"{stage}:{error_class}"] += 1

    def incr_rate(self, stage: str, outcome: str) -> None:
        self._rates[f"{stage}:{outcome}"] += 1

    def incr_tokens(self, n: int) -> None:
        self._llm_tokens += max(0, int(n))

    def incr_vp_reflection(self, result: str) -> None:
        self.incr_rate("vp_reflection", result)

    def incr_outcome(self, status: str) -> None:
        self.incr_rate("invoice_outcome", status)

    def snapshot(self) -> dict[str, Any]:
        avg_latency = {
            stage: (self._latency_sum[stage] / self._latency_count[stage])
            for stage in self._latency_count
        }
        return {
            "avg_latency_s": avg_latency,
            "errors": dict(self._errors),
            "rates": dict(self._rates),
            "llm_tokens_total": self._llm_tokens,
        }

    def persist(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2) + "\n", encoding="utf-8")

    def heartbeat(self) -> dict[str, Any]:
        """System health heartbeat for operators."""
        return {"status": "ok", "metrics": self.snapshot()}
