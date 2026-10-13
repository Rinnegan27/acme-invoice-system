#!/usr/bin/env python3
"""Live Grok CLI VP matrix: W-A → VP; Widg3tA hard reject; HV VP; clean auto."""

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

os.environ.setdefault("GALATIQ_CLI_AUTO_VP", "1")
os.environ.setdefault("GALATIQ_PROFILE", "case")

from invoice_automation.orchestration.pipeline import Pipeline  # noqa: E402

OUT = ROOT / "docs" / "release_190_e2e"
OUT.mkdir(parents=True, exist_ok=True)

CASES: list[tuple[str, str, str]] = [
    (
        "clean_auto",
        "paid",
        """Invoice Number: INV-CLI-CLEAN
Vendor: Widgets Inc.
Item: WidgetA
Qty: 2
Unit Price: $250
Total: $500
""",
    ),
    (
        "widg3ta_hard",
        "rejected",
        """Invoice Number: INV-CLI-W3
Vendor: SupplyCo
Item: Widg3tA
Qty: 3
Unit Price: $250
Total: $750
""",
    ),
    (
        "wa_vp",
        "paid",
        """Invoice Number: INV-CLI-WA
Vendor: Abbrev Co
Item: W-A
Qty: 5
Unit Price: $250
Total: $1250
""",
    ),
    (
        "hv_vp",
        "paid",
        """Invoice Number: INV-CLI-HV
Vendor: RoundVault LLC
Item: GadgetX
Qty: 3
Unit Price: $3333.3333
Total: $10000.00
""",
    ),
]


def _pass(name: str, expect: str, status: str, soft: list, reflected: bool, issues: list) -> bool:
    if status != expect:
        return False
    if name == "clean_auto":
        return not reflected and not soft
    if name == "widg3ta_hard":
        return any("unknown_item" in i for i in issues) and not reflected
    if name == "wa_vp":
        return reflected and any("sku_typo" in str(s) for s in soft)
    if name == "hv_vp":
        return reflected
    return False


def main() -> int:
    rows: list[dict] = []
    print(f"LIVE CLI VP CHECK  model={os.environ.get('XAI_MODEL', '?')}", flush=True)
    for name, expect, body in CASES:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / f"{name}.txt"
            path.write_text(body.strip() + "\n", encoding="utf-8")
            kwargs: dict = {"work_dir": root / "run", "use_grok": True, "profile": "case"}
            # Match UAT COMP-4.5: HV fixture uses strict bands so amount=$10k is the VP trigger.
            if name == "hv_vp":
                kwargs["soft_price_bands"] = False
            pipe = Pipeline(**kwargs)
            t0 = time.perf_counter()
            result = pipe.process_file(path)
            elapsed = time.perf_counter() - t0
            events = pipe.events.read_all()
            validated = next((e for e in events if e["event_type"] == "InvoiceValidated"), None)
            approved = next((e for e in events if e["event_type"] == "InvoiceApproved"), None)
            soft = list((validated or {}).get("payload", {}).get("soft_escalations") or [])
            reflected = bool(approved and approved["payload"].get("reflected"))
            issues = list(result.issues or ())
            stock = pipe.inventory.stock_levels()
            ok = _pass(name, expect, result.status, soft, reflected, issues)
            row = {
                "case": name,
                "status": result.status,
                "expect": expect,
                "issues": issues,
                "soft": soft,
                "reflected": reflected,
                "stock": stock,
                "elapsed_s": round(elapsed, 2),
                "pass": ok,
            }
            rows.append(row)
            mark = "PASS" if ok else "FAIL"
            print(
                f"{mark} {name:<14} status={result.status:<10} "
                f"reflected={reflected} soft={soft} issues={issues} "
                f"stock={stock} ({elapsed:.1f}s)",
                flush=True,
            )

    (OUT / "01_cli_vp_cases.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    n_ok = sum(1 for r in rows if r["pass"])
    print(f"Summary: {n_ok}/{len(rows)}", flush=True)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
