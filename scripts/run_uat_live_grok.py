#!/usr/bin/env python3
"""Run docs/uat_test_cases.md scenarios one-by-one with live Grok."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text().splitlines():
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from invoice_automation.orchestration.pipeline import Pipeline  # noqa: E402

OUT = ROOT / "docs" / "uat_live_grok_results.jsonl"
DATA = ROOT / "data" / "invoices"

CASES: list[tuple[str, str, str, str | tuple[str, ...]]] = [
    (
        "TC-NAME-01",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9101
Vendor: Delta Corp
Item: Widget A
Qty: 5
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NAME-02",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9102
Vendor: SupplyCo
Item: Widg3tA
Qty: 3
Unit Price: $250
Total: $750
""",
    ),
    (
        "TC-NAME-03",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9103
Vendor: Acme Partner
Item: WidgetC
Qty: 2
Unit Price: $250
Total: $500
""",
    ),
    (
        "TC-NAME-04",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9104
Vendor: CaseCo
Item: widget_a
Qty: 5
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NAME-05",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9105
Vendor: FatFinger LLC
Item: Widgiet B
Qty: 2
Unit Price: $500
Total: $1000
""",
    ),
    (
        "TC-NAME-06",
        "VP REVIEW ESCALATION",
        "vp",
        """
Invoice Number: INV-9106
Vendor: Abbrev Co
Item: W-A
Qty: 10
Unit Price: $250
Total: $2500
""",
    ),
    (
        "TC-NAME-07",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9107
Vendor: Truncate Inc
Item: WidgA
Qty: 2
Unit Price: $250
Total: $500
""",
    ),
    (
        "TC-NAME-08",
        "VP REVIEW ESCALATION",
        "vp",
        """
Invoice Number: INV-9108
Vendor: Alias Traders
Item: Widget Alpha
Qty: 1
Unit Price: $250
Total: $250
""",
    ),
    (
        "TC-NAME-09",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9109
Vendor: Noise Co
Item: W_i_d_g_e_t_A
Qty: 2
Unit Price: $250
Total: $500
""",
    ),
    (
        "TC-NAME-10",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9110
Vendor: Phonetic Co
Item: Gadget Ex
Qty: 1
Unit Price: $100
Total: $100
""",
    ),
    (
        "TC-NAME-11",
        "VP REVIEW ESCALATION",
        "vp_stop",
        """
Invoice Number: INV-9111
Vendor: Root Ambiguity Co
Item: Widget
Qty: 5
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NUM-01",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9201
Vendor: Global Logistics
Item: WidgetB
Qty: 5.5
Unit Price: $500
Total: $2750
""",
    ),
    (
        "TC-NUM-02",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9202
Vendor: Text Corp
Item: WidgetA
Qty: "Five"
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NUM-03",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9203
Vendor: Rogue Inc
Item: WidgetA
Qty: -10
Unit Price: $250
Total: $2500
""",
    ),
    (
        "TC-NUM-04",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9204
Vendor: Redundant Co
Item: WidgetA
Qty: 10 (Ten)
Unit Price: $250
Total: $2500
""",
    ),
    (
        "TC-NUM-05",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9205
Vendor: Approx Co
Item: WidgetA
Qty: ~5
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NUM-06",
        "PASS then zero-qty block",
        "flag",
        """
Invoice Number: INV-9206
Vendor: OCR Co
Item: WidgetA
Qty: O
Unit Price: $250
Total: $0
""",
    ),
    (
        "TC-NUM-07",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9207
Vendor: Percent Co
Item: WidgetA
Qty: 1,000%
Unit Price: $250
Total: $100
""",
    ),
    (
        "TC-NUM-08",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9208
Vendor: Pad Co
Item: WidgetA
Qty: 00005
Unit Price: $250
Total: $1250
""",
    ),
    (
        "TC-NUM-09",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9209
Vendor: SciNote Co
Item: WidgetB
Qty: 1e1
Unit Price: $500
Total: $5000
""",
    ),
    (
        "TC-NUM-10",
        "PASS (Auto-Fix)",
        "paid",
        """
Invoice Number: INV-9210
Vendor: UnitNoise Co
Item: WidgetA
Qty: 3 units
Unit Price: USD $250.00
Total: $750
""",
    ),
    (
        "TC-STOCK-01",
        "PASS",
        "paid",
        """
Invoice Number: INV-9301
Vendor: Manufacturing Ltd
Item: GadgetX
Qty: 5
Unit Price: $100
Total: $500
""",
    ),
    (
        "TC-STOCK-02",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9302
Vendor: Nexus Trading
Item: GadgetX
Qty: 6
Unit Price: $100
Total: $600
""",
    ),
    (
        "TC-STOCK-03",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9303
Vendor: Shadow Supply
Item: FakeItem
Qty: 1
Unit Price: $1
Total: $1
""",
    ),
    (
        "TC-STOCK-04",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9304
Vendor: ZeroQty Co
Item: GadgetX
Qty: 0
Unit Price: $100
Total: $100
""",
    ),
    (
        "TC-STOCK-05",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9305
Vendor: OffByOne Co
Item: WidgetA
Qty: 16
Unit Price: $250
Total: $4000
""",
    ),
    (
        "TC-STOCK-06",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9306
Vendor: SplitRows Co
Item: WidgetB
Qty: 1
Unit Price: $500
Item: WidgetB
Qty: 10
Unit Price: $500
Total: $5500
""",
    ),
    (
        "TC-STOCK-07",
        "PASS",
        "paid",
        """
Invoice Number: INV-9307
Vendor: Ceiling Co
Item: widgeta
Qty: 15
Unit Price: $250
Total: $3750
""",
    ),
    (
        "TC-STOCK-08",
        "PASS",
        "paid",
        """
Invoice Number: INV-9308
Vendor: Deplete Co
Item: WidgetB
Qty: 10
Unit Price: $500
Total: $5000
""",
    ),
    (
        "TC-STOCK-09",
        "FLAG",
        "flag",
        """
Invoice Number: INV-9309
Vendor: MicroFloat Co
Item: GadgetX
Qty: 5.0000001
Unit Price: $100
Total: $500
""",
    ),
    (
        "TC-COMP-4.1",
        "FLAG fail-fast before VP",
        "flag_no_vp",
        """
Invoice Number: INV-9401
Vendor: Maxi-Corp
Item: WidgetB
Qty: 25
Unit Price: $500
Total: $12500
""",
    ),
    (
        "TC-COMP-4.2",
        "FLAG math before VP",
        "flag_no_vp",
        """
Invoice Number: INV-9402
Vendor: Alpha Inc
Item: WidgetA
Qty: 10
Unit Price: $100
Total: $11000
""",
    ),
    (
        "TC-COMP-4.3",
        "FLAG/VP reject variant",
        "flag",
        """
Invoice Number: INV-9403
Vendor: Premium Vendors
Item: WidgetA-Premium
Qty: 2
Unit Price: $4000
Total: $8000
""",
    ),
    (
        "TC-COMP-4.4",
        "FLAG atomic overstock",
        "flag",
        """
Invoice Number: INV-9404
Vendor: MultiLine Co
Item: WidgetA
Qty: 15
Unit Price: $250
Item: WidgetB
Qty: 12
Unit Price: $500
Item: GadgetX
Qty: 1
Unit Price: $100
Total: $9850
""",
    ),
    (
        "TC-COMP-4.5",
        "PASS via VP",
        "paid_vp",
        """
Invoice Number: INV-9405
Vendor: RoundVault LLC
Item: GadgetX
Qty: 3
Unit Price: $3333.3333
Total: $10000.00
""",
    ),
    (
        "TC-COMP-4.6",
        "PASS injection safe",
        "paid",
        """
Invoice Number: INV-9406
Vendor: '; DROP TABLE inventory; --
Item: WidgetA
Qty: 1
Unit Price: $250
Total: $250
""",
    ),
    # Real-file sequences on one Pipeline (same work_dir). Body is a tuple of file names.
    (
        "TC-CASE-REV-01",
        "PASS (revision delta)",
        "paid",
        ("invoice_1004.json", "invoice_1004_revised.json"),
    ),
    (
        "TC-CASE-TWIN-01",
        "PASS (twin, no 2nd draw)",
        "paid",
        ("invoice_1011.txt", "invoice_1011.pdf"),
    ),
]


def run_seq(tc_id: str, names: tuple[str, ...]) -> dict:
    """Process real data files in order on one Pipeline; check stock deltas."""
    with tempfile.TemporaryDirectory() as d:
        pipe = Pipeline(work_dir=Path(d) / "run", use_grok=True, profile="case")
        start = pipe.inventory.stock_levels()
        t0 = time.perf_counter()
        results = []
        stocks = []
        for name in names:
            results.append(pipe.process_file(DATA / name))
            stocks.append(pipe.inventory.stock_levels())
        elapsed = time.perf_counter() - t0
        problems = [
            f"{r.source_path.rsplit('/', 1)[-1]}={r.status}" for r in results if r.status != "paid"
        ]
        if tc_id == "TC-CASE-REV-01" and not problems:
            if stocks[1]["GadgetX"] != start["GadgetX"] - 5:
                problems.append("GadgetX delta != 5")
            if any(stocks[1][k] != stocks[0][k] for k in ("WidgetA", "WidgetB")):
                problems.append("second draw on unchanged lines")
        if tc_id == "TC-CASE-TWIN-01" and not problems and stocks[1] != stocks[0]:
            problems.append("twin drew stock again")
        return {
            "status": "paid" if not problems else "failed",
            "issues": problems,
            "soft": [],
            "reflected": False,
            "reason": "; ".join(problems) or "sequence ok",
            "elapsed": round(elapsed, 2),
        }


def run_one(tc_id: str, body: str | tuple[str, ...], *, soft_bands: bool) -> dict:
    if isinstance(body, tuple):
        return run_seq(tc_id, body)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        path = root / f"{tc_id}.txt"
        path.write_text(body.strip() + "\n", encoding="utf-8")
        kwargs: dict = {"work_dir": root / "run", "use_grok": True, "profile": "case"}
        if not soft_bands:
            kwargs["soft_price_bands"] = False
        pipe = Pipeline(**kwargs)
        t0 = time.perf_counter()
        result = pipe.process_file(path)
        elapsed = time.perf_counter() - t0
        events = pipe.events.read_all()
        approved = next((e for e in events if e["event_type"] == "InvoiceApproved"), None)
        validated = next((e for e in events if e["event_type"] == "InvoiceValidated"), None)
        rejected_ev = [e for e in events if e["event_type"] == "InvoiceRejected"]
        soft = list((validated or {}).get("payload", {}).get("soft_escalations") or [])
        reflected = bool(approved and approved["payload"].get("reflected"))
        if approved:
            reason = str(approved["payload"].get("reason") or "")
        elif rejected_ev:
            reason = str(rejected_ev[-1]["payload"].get("reason") or "")
        else:
            reason = result.approval_reason or ""
        return {
            "status": result.status,
            "issues": list(result.issues or ()),
            "soft": soft,
            "reflected": reflected,
            "reason": reason[:200],
            "elapsed": round(elapsed, 2),
        }


def judge(rule: str, info: dict) -> tuple[bool, str]:
    st = info["status"]
    issues = " ".join(info["issues"])
    soft = " ".join(str(s) for s in info["soft"])
    blob = f"{issues} {soft} {info['reason']}"
    if rule == "paid":
        return st == "paid", "paid" if st == "paid" else f"got {st}"
    if rule == "paid_vp":
        ok = st == "paid" and info["reflected"]
        return ok, "paid+VP" if ok else f"got {st} reflected={info['reflected']}"
    if rule == "flag":
        ok = st in {"rejected", "failed"}
        return ok, st if ok else f"got {st} (expected flag)"
    if rule == "flag_no_vp":
        ok = st in {"rejected", "failed"} and not info["reflected"]
        return ok, f"{st} without VP" if ok else f"got {st} reflected={info['reflected']}"
    if rule == "vp":
        if st == "paid" and (info["reflected"] or soft):
            return True, "VP then paid"
        if st == "rejected" and (info["reflected"] or soft):
            return True, "VP then rejected"
        if soft and st in {"paid", "rejected"}:
            return True, f"soft → {st}"
        return False, f"got {st} soft={soft or '-'} reflected={info['reflected']}"
    if rule == "vp_stop":
        ok = st == "rejected" and (
            info["reflected"] or "ambiguous" in blob or "sku_typo" in blob or "unknown" in blob
        )
        return ok, f"stop ({st})" if ok else f"got {st}"
    return False, f"unknown rule {rule}"


def main() -> int:
    start = os.environ.get("UAT_START", "")
    only = os.environ.get("UAT_ONLY", "")
    cases = CASES
    if only:
        want = {x.strip() for x in only.split(",") if x.strip()}
        cases = [c for c in cases if c[0] in want]
    elif start:
        idx = next((i for i, c in enumerate(cases) if c[0] == start), 0)
        cases = cases[idx:]

    print(f"LIVE GROK UAT  model={os.environ.get('XAI_MODEL', '?')}  n={len(cases)}", flush=True)
    print(f"{'CASE':<14} {'EXPECTED':<28} {'ACTUAL':<10} {'MATCH':<6} {'s':>6}  DETAIL", flush=True)
    print("-" * 110, flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Fresh file when starting from the beginning
    if not start and not only:
        OUT.write_text("", encoding="utf-8")

    ok_n = 0
    fails: list[str] = []
    for tc_id, expected, rule, body in cases:
        soft_bands = tc_id != "TC-COMP-4.5"
        try:
            info = run_one(tc_id, body, soft_bands=soft_bands)
            matched, detail = judge(rule, info)
        except Exception as exc:  # noqa: BLE001
            info = {
                "status": "error",
                "issues": [],
                "soft": [],
                "reflected": False,
                "reason": str(exc),
                "elapsed": 0.0,
            }
            matched, detail = False, f"ERROR: {exc}"
            traceback.print_exc()
        match = "PASS" if matched else "FAIL"
        if matched:
            ok_n += 1
        else:
            fails.append(tc_id)
        extra = []
        if info.get("issues"):
            extra.append("issues=" + ",".join(info["issues"][:3]))
        if info.get("soft"):
            extra.append("soft=" + ",".join(str(s) for s in info["soft"][:2]))
        if info.get("reflected"):
            extra.append("VP=yes")
        line = (
            f"{tc_id:<14} {expected:<28} {info['status']:<10} {match:<6} "
            f"{info.get('elapsed', 0):6.1f}  {detail}"
        )
        if extra:
            line += " | " + "; ".join(extra)
        print(line, flush=True)
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "tc_id": tc_id,
                        "expected": expected,
                        "match": match,
                        "detail": detail,
                        **info,
                    }
                )
                + "\n"
            )

    print("-" * 110, flush=True)
    print(f"Summary: {ok_n}/{len(cases)} match expected (LIVE GROK)", flush=True)
    if fails:
        print("FAILS: " + ", ".join(fails), flush=True)
    print(f"Results: {OUT}", flush=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
