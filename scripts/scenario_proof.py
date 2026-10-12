#!/usr/bin/env python3
"""Build the case-brief scenario proof artifact.

Run
---
uv run python scripts/scenario_proof.py

Output
------
docs/scenario_proof.json
docs/scenario_proof.md

Notes
-----
This script uses the offline stub. It does not call Grok.
Each row maps to the scenario table in the Galatiq case README.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Permit secret for local offline runs. Do not use this value in production.
os.environ.setdefault("GALATIQ_PERMIT_SECRET", "scenario-proof-local-secret-do-not-use")
# Case README matrix needs soft price bands (not prod hardening).
os.environ["GALATIQ_PROFILE"] = "case"

from invoice_automation.orchestration.pipeline import Pipeline  # noqa: E402

OUT_DIR = ROOT / "docs"
DATA_DIR = ROOT / "data" / "invoices"


@dataclass(frozen=True)
class ScenarioRow:
    """One row from the case README scenario table."""

    scenario: str
    invoice_id: str
    file_name: str
    expect_status: str
    expect_issue_substr: str | None
    brief_note: str


# Case README scenario table (minimum set named in the brief).
SCENARIOS: tuple[ScenarioRow, ...] = (
    ScenarioRow(
        scenario="Normal order within stock",
        invoice_id="INV-1001",
        file_name="invoice_1001.txt",
        expect_status="paid",
        expect_issue_substr=None,
        brief_note="Items found, quantities valid — passes validation",
    ),
    ScenarioRow(
        scenario="Normal order within stock",
        invoice_id="INV-1004",
        file_name="invoice_1004.json",
        expect_status="paid",
        expect_issue_substr=None,
        brief_note="Items found, quantities valid — passes validation",
    ),
    ScenarioRow(
        scenario="Normal order within stock",
        invoice_id="INV-1006",
        file_name="invoice_1006.csv",
        expect_status="paid",
        expect_issue_substr=None,
        brief_note="Items found, quantities valid — passes validation",
    ),
    ScenarioRow(
        scenario="Quantity exceeds stock",
        invoice_id="INV-1002",
        file_name="invoice_1002.txt",
        expect_status="rejected",
        expect_issue_substr="insufficient_stock",
        brief_note="INV-1002 requests 20× GadgetX, only 5 in stock",
    ),
    ScenarioRow(
        scenario="Fraudulent / zero-stock item",
        invoice_id="INV-1003",
        file_name="invoice_1003.txt",
        expect_status="rejected",
        expect_issue_substr="zero_stock",
        brief_note="FakeItem has 0 stock",
    ),
    ScenarioRow(
        scenario="Item not in database",
        invoice_id="INV-1008",
        file_name="invoice_1008.txt",
        expect_status="rejected",
        expect_issue_substr="unknown_item",
        brief_note="SuperGizmo / MegaSprocket not in seed",
    ),
    ScenarioRow(
        scenario="Item not in database",
        invoice_id="INV-1016",
        file_name="invoice_1016.json",
        expect_status="rejected",
        expect_issue_substr="unknown_item",
        brief_note="WidgetC not in seed",
    ),
    ScenarioRow(
        scenario="Invalid data",
        invoice_id="INV-1009",
        file_name="invoice_1009.json",
        expect_status="rejected",
        expect_issue_substr="invalid_quantity",
        brief_note="Negative quantity — data integrity issue",
    ),
)


def _run_one(pipe: Pipeline, file_name: str) -> dict[str, object]:
    path = DATA_DIR / file_name
    result = pipe.process_file(path)
    return {
        "file_name": file_name,
        "invoice_id": result.invoice_id,
        "status": result.status,
        "issues": list(result.issues),
        "approval_reason": result.approval_reason,
        "paid": result.status == "paid",
    }


def _row_ok(row: ScenarioRow, actual: dict[str, object]) -> tuple[bool, str]:
    status = str(actual.get("status") or "")
    issues = [str(i) for i in (actual.get("issues") or [])]  # type: ignore[arg-type]
    if status != row.expect_status:
        return False, f"status want={row.expect_status} got={status}"
    if row.expect_issue_substr is not None:
        joined = " ".join(issues)
        if row.expect_issue_substr not in joined:
            return False, f"issues missing {row.expect_issue_substr!r}; got={issues}"
    return True, ""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scenario_proof_") as tmp:
        work = Path(tmp)
        pipe = Pipeline(work_dir=work, use_grok=False, profile="case")
        results: list[dict[str, object]] = []
        all_ok = True
        for row in SCENARIOS:
            path = DATA_DIR / row.file_name
            if not path.is_file():
                entry = {
                    **asdict(row),
                    "passed": False,
                    "message": f"missing file: {path}",
                    "actual": {},
                }
                results.append(entry)
                all_ok = False
                continue
            # Reseed stock between rows so post-pay decrements do not poison later cases.
            pipe.inventory.reseed()
            actual = _run_one(pipe, row.file_name)
            passed, message = _row_ok(row, actual)
            if not passed:
                all_ok = False
            results.append(
                {
                    **asdict(row),
                    "passed": passed,
                    "message": message,
                    "actual": actual,
                }
            )

    report = {
        "ok": all_ok,
        "source": "https://github.com/galatiq-ai/galatiq-case-invoices",
        "engine": "offline stub (--llm=stub)",
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        "rows": results,
    }

    json_path = OUT_DIR / "scenario_proof.json"
    md_path = OUT_DIR / "scenario_proof.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {md_path.relative_to(ROOT)}")
    print(f"Result: {report['passed']}/{report['total']} passed; ok={all_ok}")
    return 0 if all_ok else 1


def _to_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Case brief scenario proof",
        "",
        "This file is generated. Do not edit by hand.",
        "",
        f"- Engine: {report['engine']}",
        f"- Passed: {report['passed']}/{report['total']}",
        f"- ok: {report['ok']}",
        f"- Source brief: {report['source']}",
        "",
        "| Scenario | Invoice | File | Expected | Actual status | Issues | Pass |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:  # type: ignore[assignment]
        actual = row.get("actual") or {}
        issues = actual.get("issues") or []
        issue_s = ", ".join(str(i) for i in issues) if issues else "—"
        lines.append(
            "| {scenario} | {invoice_id} | `{file}` | {expect} | {status} | {issues} | {ok} |".format(
                scenario=row["scenario"],
                invoice_id=row["invoice_id"],
                file=row["file_name"],
                expect=row["expect_status"]
                + (f" + `{row['expect_issue_substr']}`" if row.get("expect_issue_substr") else ""),
                status=actual.get("status", "—"),
                issues=issue_s,
                ok="yes" if row["passed"] else "no",
            )
        )
    lines.append("")
    lines.append("Regenerate with:")
    lines.append("")
    lines.append("```bash")
    lines.append("make scenario-proof")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
