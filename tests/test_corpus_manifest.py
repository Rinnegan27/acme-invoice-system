"""Golden-manifest E2E: every corpus file matches expected status/issues."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.black_box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "invoices"
MANIFEST = ROOT / "data" / "corpus_manifest.jsonl"


def _load_manifest() -> list[dict]:
    rows = [
        json.loads(line)
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows, "corpus manifest is empty"
    return rows


@pytest.fixture(scope="module")
def manifest_rows() -> list[dict]:
    return _load_manifest()


def test_manifest_covers_all_invoice_files(manifest_rows: list[dict]) -> None:
    on_disk = {p.name for p in DATA.iterdir() if p.is_file()}
    in_manifest = {row["file"] for row in manifest_rows}
    assert on_disk == in_manifest
    assert len(on_disk) == 100


@pytest.mark.parametrize("row", _load_manifest(), ids=lambda r: r["file"])
def test_manifest_row_offline(row: dict, tmp_path: Path) -> None:
    path = DATA / row["file"]
    assert path.is_file(), row["file"]
    result = Pipeline(
        work_dir=tmp_path / row["file"].replace(".", "_"), use_grok=False
    ).process_file(path)
    allowed = set(row.get("allow_statuses") or [row["expect_status"]])
    assert result.status in allowed, (
        f"{row['file']}: status={result.status!r} not in {sorted(allowed)}; "
        f"issues={list(result.issues)}"
    )
    substr = row.get("expect_issue_substr")
    if substr:
        joined = " ".join(result.issues)
        assert any(substr in issue for issue in result.issues), (
            f"{row['file']}: expected issue substring {substr!r} in {list(result.issues)} "
            f"(joined={joined!r})"
        )
