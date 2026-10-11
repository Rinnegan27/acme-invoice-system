"""Smoke E2E over the full 100-file flat corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.black_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"
MANIFEST = ROOT / "data" / "corpus_manifest.jsonl"


def _load_manifest() -> list[dict]:
    return [
        json.loads(line)
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_corpus_has_exactly_100_files() -> None:
    files = [p for p in DATA.iterdir() if p.is_file()]
    assert len(files) == 100
    assert MANIFEST.is_file()
    assert len(_load_manifest()) == 100


def test_process_directory_smoke_offline(tmp_path: Path) -> None:
    """Full-directory offline run: no crash, mixed paid/rejected outcomes."""
    pipe = Pipeline(work_dir=tmp_path / "smoke", use_grok=False)
    results = pipe.process_directory(DATA)

    # PDF twins with .txt siblings are skipped by process_directory.
    assert len(results) >= 90
    statuses = Counter(r.status for r in results)
    assert statuses.get("paid", 0) >= 1
    assert statuses.get("rejected", 0) >= 1
    # Malformed buckets may surface as failed; never leave everything unknown.
    assert (
        statuses.get("unknown", 0) == 0
        or statuses.get("paid", 0) + statuses.get("rejected", 0) >= 50
    )

    by_name = {Path(r.source_path).name: r for r in results}
    manifest = _load_manifest()
    categories_seen: set[str] = set()
    for row in manifest:
        name = row["file"]
        if name not in by_name:
            continue  # skipped PDF twin
        categories_seen.add(row["category"])
    # Stress set should hit the main category families.
    for required in ("stp", "insufficient_stock", "zero_stock", "unknown_item", "high_value"):
        assert required in categories_seen


def test_new_pdf_only_stem_processes(tmp_path: Path) -> None:
    """PDF-only generated stems must exercise pdfplumber (no TXT twin)."""
    pdfs = sorted(p for p in DATA.glob("invoice_11*.pdf") if not (DATA / f"{p.stem}.txt").exists())
    assert pdfs, "expected at least one PDF-only generated invoice"
    result = Pipeline(work_dir=tmp_path / "pdf", use_grok=False).process_file(pdfs[0])
    assert result.status in {"paid", "rejected", "failed", "approved"}
    assert any(e.get("event_type") == "InvoiceReceived" for e in result.events)
