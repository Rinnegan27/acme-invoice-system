#!/usr/bin/env python3
"""Stateful inventory ledger: process case invoices sequentially with live Grok.

Processes every file under the Galatiq case brief corpus (invoice_1001 …
invoice_1016, including format twins / revisions) against one shared
inventory DB. After each file, records pipeline status and remaining stock.

Environment
-----------
LEDGER_LLM : ``grok`` (default) or ``stub``
STOCK_MULT : multiply case-brief seed quantities (default ``1``). FakeItem
    stays 0 unless STOCK_SCALE_ZERO=1.
    At 1×, INV-1002 (20× GadgetX) must reject ``insufficient_stock``.
    At ≥4× (or 15×), the same file can pay — seed-scale semantics, not a bug.

Outputs
-------
docs/stateful_ledger.md / .jsonl   (or ``_Nx`` suffix when STOCK_MULT != 1)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text().splitlines():
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from invoice_automation.adapters.sqlite_db import connect  # noqa: E402
from invoice_automation.orchestration.pipeline import Pipeline  # noqa: E402

DATA = ROOT / "data" / "invoices"

# Exact upstream set: https://github.com/galatiq-ai/galatiq-case-invoices/tree/main/data/invoices
CASE_CORE_ORDER: tuple[str, ...] = (
    "invoice_1001.txt",
    "invoice_1002.txt",
    "invoice_1003.txt",
    "invoice_1004.json",
    "invoice_1004_revised.json",
    "invoice_1005.json",
    "invoice_1006.csv",
    "invoice_1007.csv",
    "invoice_1008.txt",
    "invoice_1009.json",
    "invoice_1010.txt",
    "invoice_1011.txt",
    "invoice_1011.pdf",
    "invoice_1012.txt",
    "invoice_1012.pdf",
    "invoice_1013.json",
    "invoice_1013.pdf",
    "invoice_1014.xml",
    "invoice_1015.csv",
    "invoice_1016.json",
)

BASE_SEED = {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0}


def _stock_mult() -> int:
    try:
        return max(1, int(os.environ.get("STOCK_MULT", "1")))
    except ValueError:
        return 1


def _scaled_seed(mult: int) -> dict[str, int]:
    scale_zero = os.environ.get("STOCK_SCALE_ZERO", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    out: dict[str, int] = {}
    for sku, qty in BASE_SEED.items():
        if qty == 0 and not scale_zero:
            out[sku] = 0
        else:
            out[sku] = qty * mult
    return out


def _apply_seed(inventory_db: Path, seed: dict[str, int]) -> None:
    with connect(inventory_db) as conn:
        for sku, qty in seed.items():
            conn.execute(
                "INSERT INTO inventory(item, stock) VALUES (?, ?) "
                "ON CONFLICT(item) DO UPDATE SET stock = excluded.stock",
                (sku, qty),
            )
        conn.commit()


def _fmt_stock(stock: dict[str, int]) -> str:
    return (
        f"`WidgetA: {stock.get('WidgetA', 0)}`, "
        f"`WidgetB: {stock.get('WidgetB', 0)}`, "
        f"`GadgetX: {stock.get('GadgetX', 0)}`, "
        f"`FakeItem: {stock.get('FakeItem', 0)}`"
    )


def _delta(before: dict[str, int], after: dict[str, int]) -> str:
    parts = []
    for sku in ("WidgetA", "WidgetB", "GadgetX", "FakeItem"):
        d = after.get(sku, 0) - before.get(sku, 0)
        if d:
            parts.append(f"{sku}{d:+d}")
    return ", ".join(parts) if parts else "no stock change"


def _write_markdown(
    rows: list[dict],
    *,
    seed: dict[str, int],
    mult: int,
    out_md: Path,
) -> None:
    lines: list[str] = []
    title = "Stateful Ledger Transformation (Case Core 1001–1016)"
    if mult != 1:
        title += f" — {mult}× seed"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        "Sequential live-Grok run over the Galatiq case invoice set "
        "([data/invoices](https://github.com/galatiq-ai/galatiq-case-invoices/tree/main/data/invoices)). "
        "One shared inventory DB; stock is measured after each file."
    )
    if mult != 1:
        lines.append("")
        lines.append(
            f"Seed is case-brief baseline × **{mult}** "
            f"(FakeItem left at 0 unless ``STOCK_SCALE_ZERO=1``)."
        )
    lines.append("")
    lines.append("### Initial baseline (T₀)")
    lines.append("")
    for sku, qty in seed.items():
        lines.append(f"- **{sku}:** {qty} units")
    lines.append("")
    lines.append("### Execution matrix")
    lines.append("")
    lines.append(
        "| Step | File | Format | Invoice ID | Status | Issues / notes | Stock delta | Resulting DB state |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    lines.append(
        f"| **0** | — | — | — | seed | Case brief inventory seed ×{mult} | — | {_fmt_stock(seed)} |"
    )
    for row in rows:
        issues = ", ".join(row["issues"][:4]) if row["issues"] else "—"
        if row.get("reason"):
            issues = (issues + "; " if issues != "—" else "") + row["reason"][:80]
        lines.append(
            f"| **{row['step']}** | `{row['file']}` | **{row['format']}** | "
            f"**{row['invoice_id'] or '—'}** | `{row['status']}` | {issues} | "
            f"{row['delta']} | {_fmt_stock(row['stock_after'])} |"
        )
    lines.append("")
    terminal = rows[-1]["stock_after"] if rows else seed
    lines.append("### Terminal stock")
    lines.append("")
    for sku in ("WidgetA", "WidgetB", "GadgetX", "FakeItem"):
        lines.append(f"- **{sku}:** {terminal.get(sku, 0)} units remaining")
    lines.append("")
    lines.append(
        f"_Generated by `scripts/run_stateful_ledger_live_grok.py` "
        f"(model={os.environ.get('XAI_MODEL', 'grok')}, STOCK_MULT={mult})._"
    )
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    use_grok = os.environ.get("LEDGER_LLM", "grok").strip().lower() != "stub"
    mult = _stock_mult()
    seed = _scaled_seed(mult)
    suffix = "" if mult == 1 else f"_{mult}x"
    out_jsonl = ROOT / "docs" / f"stateful_ledger{suffix}_results.jsonl"
    out_md = ROOT / "docs" / f"stateful_ledger{suffix}.md"

    missing = [f for f in CASE_CORE_ORDER if not (DATA / f).exists()]
    if missing:
        print("Missing case files:", ", ".join(missing), flush=True)
        return 2

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_jsonl.write_text("", encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "ledger"
        pipe = Pipeline(work_dir=work, use_grok=use_grok, profile="case")
        _apply_seed(work / "inventory.db", seed)
        stock0 = pipe.inventory.stock_levels()
        print(
            f"STATEFUL LEDGER  llm={'grok' if use_grok else 'stub'}  "
            f"model={os.environ.get('XAI_MODEL', '?')}  STOCK_MULT={mult}  T0={stock0}",
            flush=True,
        )
        assert stock0 == seed, f"seed mismatch: {stock0} != {seed}"

        rows: list[dict] = []
        before = dict(stock0)
        for step, name in enumerate(CASE_CORE_ORDER, start=1):
            path = DATA / name
            t0 = time.perf_counter()
            try:
                result = pipe.process_file(path)
                err = ""
            except Exception as exc:  # noqa: BLE001
                result = None
                err = str(exc)
            elapsed = time.perf_counter() - t0
            after = pipe.inventory.stock_levels()
            neg = {k: v for k, v in after.items() if v < 0}
            row = {
                "step": step,
                "file": name,
                "format": path.suffix.lstrip(".").upper() or "?",
                "invoice_id": getattr(result, "invoice_id", "") or "",
                "status": getattr(result, "status", "error"),
                "issues": list(getattr(result, "issues", ()) or ()),
                "reason": (getattr(result, "approval_reason", "") or err)[:200],
                "stock_before": before,
                "stock_after": after,
                "delta": _delta(before, after),
                "elapsed_s": round(elapsed, 2),
                "negative_stock": neg,
                "stock_mult": mult,
            }
            rows.append(row)
            with out_jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(
                f"[{step:02d}/{len(CASE_CORE_ORDER)}] {name:<28} "
                f"{row['status']:<10} {row['delta']:<36} "
                f"DB={_fmt_stock(after)}  ({elapsed:.1f}s)",
                flush=True,
            )
            if neg:
                print(f"  ERROR negative stock: {neg}", flush=True)
            before = dict(after)

        _write_markdown(rows, seed=seed, mult=mult, out_md=out_md)
        print(f"Wrote {out_md}", flush=True)
        print(f"Wrote {out_jsonl}", flush=True)

        failures: list[str] = []
        for row in rows:
            if row["negative_stock"]:
                failures.append(f"step {row['step']}: negative {row['negative_stock']}")
        if any(row["status"] == "error" for row in rows):
            failures.append("one or more steps errored")
        if failures:
            print("CHECK FAILS:", "; ".join(failures), flush=True)
            return 1
        print("CHECK OK: non-negative stock throughout", flush=True)
        print(f"TERMINAL: {_fmt_stock(rows[-1]['stock_after'])}", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
