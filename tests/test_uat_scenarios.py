"""UAT scenarios from docs/uat_test_cases.md (offline stub pipeline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_automation.orchestration.pipeline import Pipeline

pytestmark = pytest.mark.black_box


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def _run(tmp: Path, name: str, body: str):
    path = _write(tmp, name, body)
    pipe = Pipeline(work_dir=tmp / f"run_{name}", use_grok=False, profile="case")
    return pipe.process_file(path)


# --- 1. Wrong name -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tc_id", "body", "expect"),
    [
        (
            "TC-NAME-01",
            """
            Invoice Number: INV-9101
            Vendor: Delta Corp
            Item: Widget A
            Qty: 5
            Unit Price: $250
            Total: $1250
            """,
            "paid",
        ),
        (
            "TC-NAME-02",
            """
            Invoice Number: INV-9102
            Vendor: SupplyCo
            Item: Widg3tA
            Qty: 3
            Unit Price: $250
            Total: $750
            """,
            "rejected",
        ),
        (
            "TC-NAME-03",
            """
            Invoice Number: INV-9103
            Vendor: Acme Partner
            Item: WidgetC
            Qty: 2
            Unit Price: $250
            Total: $500
            """,
            "rejected",
        ),
        (
            "TC-NAME-04",
            """
            Invoice Number: INV-9104
            Vendor: CaseCo
            Item: widget_a
            Qty: 5
            Unit Price: $250
            Total: $1250
            """,
            "paid",
        ),
        (
            "TC-NAME-05",
            """
            Invoice Number: INV-9105
            Vendor: FatFinger LLC
            Item: Widgiet B
            Qty: 2
            Unit Price: $500
            Total: $1000
            """,
            "paid",
        ),
        (
            "TC-NAME-06",
            """
            Invoice Number: INV-9106
            Vendor: Abbrev Co
            Item: W-A
            Qty: 10
            Unit Price: $250
            Total: $2500
            """,
            "rejected",  # short abbreviations are not catalog SKUs
        ),
        (
            "TC-NAME-07",
            """
            Invoice Number: INV-9107
            Vendor: Truncate Inc
            Item: WidgA
            Qty: 2
            Unit Price: $250
            Total: $500
            """,
            "paid",
        ),
        (
            "TC-NAME-08",
            """
            Invoice Number: INV-9108
            Vendor: Alias Traders
            Item: Widget Alpha
            Qty: 1
            Unit Price: $250
            Total: $250
            """,
            "paid",  # stub VP approves alias review
        ),
        (
            "TC-NAME-09",
            """
            Invoice Number: INV-9109
            Vendor: Noise Co
            Item: W_i_d_g_e_t_A
            Qty: 2
            Unit Price: $250
            Total: $500
            """,
            "paid",
        ),
        (
            "TC-NAME-10",
            """
            Invoice Number: INV-9110
            Vendor: Phonetic Co
            Item: Gadget Ex
            Qty: 1
            Unit Price: $100
            Total: $100
            """,
            "paid",
        ),
        (
            "TC-NAME-11",
            """
            Invoice Number: INV-9111
            Vendor: Root Ambiguity Co
            Item: Widget
            Qty: 5
            Unit Price: $250
            Total: $1250
            """,
            "rejected",  # VP rejects ambiguous WidgetA/WidgetB root
        ),
    ],
)
def test_uat_name_cases(tmp_path: Path, tc_id: str, body: str, expect: str) -> None:
    result = _run(tmp_path, f"{tc_id}.txt", body)
    assert result.status == expect, f"{tc_id}: {result.status} issues={result.issues}"


# --- 2. Wrong number ---------------------------------------------------------


@pytest.mark.parametrize(
    ("tc_id", "body", "expect"),
    [
        (
            "TC-NUM-01",
            """
            Invoice Number: INV-9201
            Vendor: Global Logistics
            Item: WidgetB
            Qty: 5.5
            Unit Price: $500
            Total: $2750
            """,
            "failed",
        ),
        (
            "TC-NUM-02",
            """
            Invoice Number: INV-9202
            Vendor: Text Corp
            Item: WidgetA
            Qty: "Five"
            Unit Price: $250
            Total: $1250
            """,
            "paid",
        ),
        (
            "TC-NUM-03",
            """
            Invoice Number: INV-9203
            Vendor: Rogue Inc
            Item: WidgetA
            Qty: -10
            Unit Price: $250
            Total: $2500
            """,
            "rejected",
        ),
        (
            "TC-NUM-04",
            """
            Invoice Number: INV-9204
            Vendor: Redundant Co
            Item: WidgetA
            Qty: 10 (Ten)
            Unit Price: $250
            Total: $2500
            """,
            "paid",
        ),
        (
            "TC-NUM-05",
            """
            Invoice Number: INV-9205
            Vendor: Approx Co
            Item: WidgetA
            Qty: ~5
            Unit Price: $250
            Total: $1250
            """,
            "failed",
        ),
        (
            "TC-NUM-06",
            """
            Invoice Number: INV-9206
            Vendor: OCR Co
            Item: WidgetA
            Qty: O
            Unit Price: $250
            Total: $0
            """,
            "rejected",  # qty 0 → invalid_quantity
        ),
        (
            "TC-NUM-07",
            """
            Invoice Number: INV-9207
            Vendor: Percent Co
            Item: WidgetA
            Qty: 1,000%
            Unit Price: $250
            Total: $100
            """,
            "failed",
        ),
        (
            "TC-NUM-08",
            """
            Invoice Number: INV-9208
            Vendor: Pad Co
            Item: WidgetA
            Qty: 00005
            Unit Price: $250
            Total: $1250
            """,
            "paid",
        ),
        (
            "TC-NUM-09",
            """
            Invoice Number: INV-9209
            Vendor: SciNote Co
            Item: WidgetB
            Qty: 1e1
            Unit Price: $500
            Total: $5000
            """,
            "paid",
        ),
        (
            "TC-NUM-10",
            """
            Invoice Number: INV-9210
            Vendor: UnitNoise Co
            Item: WidgetA
            Qty: 3 units
            Unit Price: USD $250.00
            Total: $750
            """,
            "paid",
        ),
    ],
)
def test_uat_num_cases(tmp_path: Path, tc_id: str, body: str, expect: str) -> None:
    result = _run(tmp_path, f"{tc_id}.txt", body)
    assert result.status == expect, f"{tc_id}: {result.status} issues={result.issues}"


# --- 3. Stock boundaries -----------------------------------------------------


@pytest.mark.parametrize(
    ("tc_id", "body", "expect"),
    [
        (
            "TC-STOCK-01",
            """
            Invoice Number: INV-9301
            Vendor: Manufacturing Ltd
            Item: GadgetX
            Qty: 5
            Unit Price: $100
            Total: $500
            """,
            "paid",
        ),
        (
            "TC-STOCK-02",
            """
            Invoice Number: INV-9302
            Vendor: Nexus Trading
            Item: GadgetX
            Qty: 6
            Unit Price: $100
            Total: $600
            """,
            "rejected",
        ),
        (
            "TC-STOCK-03",
            """
            Invoice Number: INV-9303
            Vendor: Shadow Supply
            Item: FakeItem
            Qty: 1
            Unit Price: $1
            Total: $1
            """,
            "rejected",
        ),
        (
            "TC-STOCK-04",
            """
            Invoice Number: INV-9304
            Vendor: ZeroQty Co
            Item: GadgetX
            Qty: 0
            Unit Price: $100
            Total: $100
            """,
            "rejected",
        ),
        (
            "TC-STOCK-05",
            """
            Invoice Number: INV-9305
            Vendor: OffByOne Co
            Item: WidgetA
            Qty: 16
            Unit Price: $250
            Total: $4000
            """,
            "rejected",
        ),
        (
            "TC-STOCK-06",
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
            "rejected",
        ),
        (
            "TC-STOCK-07",
            """
            Invoice Number: INV-9307
            Vendor: Ceiling Co
            Item: widgeta
            Qty: 15
            Unit Price: $250
            Total: $3750
            """,
            "paid",
        ),
        (
            "TC-STOCK-08",
            """
            Invoice Number: INV-9308
            Vendor: Deplete Co
            Item: WidgetB
            Qty: 10
            Unit Price: $500
            Total: $5000
            """,
            "paid",
        ),
        (
            "TC-STOCK-09",
            """
            Invoice Number: INV-9309
            Vendor: MicroFloat Co
            Item: GadgetX
            Qty: 5.0000001
            Unit Price: $100
            Total: $500
            """,
            "failed",
        ),
    ],
)
def test_uat_stock_cases(tmp_path: Path, tc_id: str, body: str, expect: str) -> None:
    result = _run(tmp_path, f"{tc_id}.txt", body)
    assert result.status == expect, f"{tc_id}: {result.status} issues={result.issues}"


# --- 4. Compound scenarios ---------------------------------------------------


def test_uat_compound_4_1_overstock_before_vp(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-COMP-41.txt",
        """
        Invoice Number: INV-9401
        Vendor: Maxi-Corp
        Item: WidgetB
        Qty: 25
        Unit Price: $500
        Total: $12500
        """,
    )
    assert result.status == "rejected"
    assert any("insufficient_stock" in i for i in result.issues)


def test_uat_compound_4_2_ghost_phantom_total(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-COMP-42.txt",
        """
        Invoice Number: INV-9402
        Vendor: Alpha Inc
        Item: WidgetA
        Qty: 10
        Unit Price: $100
        Total: $11000
        """,
    )
    assert result.status == "rejected"
    assert any("amount_line_mismatch" in i for i in result.issues)


def test_uat_compound_4_3_sneaky_suffix(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-COMP-43.txt",
        """
        Invoice Number: INV-9403
        Vendor: Premium Vendors
        Item: WidgetA-Premium
        Qty: 2
        Unit Price: $4000
        Total: $8000
        """,
    )
    assert result.status == "rejected"
    blob = " ".join(result.issues) + " " + (result.approval_reason or "")
    assert "sku_variant_review" in blob or "variant" in blob.lower()


def test_uat_compound_4_4_atomic_overstock(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-COMP-44.txt",
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
    )
    assert result.status == "rejected"
    assert any("insufficient_stock" in i for i in result.issues)


def test_uat_compound_4_5_microcurrency_vp(tmp_path: Path) -> None:
    pipe_dir = tmp_path / "run_c45"
    path = _write(
        tmp_path,
        "TC-COMP-45.txt",
        """
        Invoice Number: INV-9405
        Vendor: RoundVault LLC
        Item: GadgetX
        Qty: 3
        Unit Price: $3333.3333
        Total: $10000.00
        """,
    )
    pipe = Pipeline(
        work_dir=pipe_dir, use_grok=False, profile="case", soft_price_bands=False
    )
    result = pipe.process_file(path)
    assert result.status == "paid", f"issues={result.issues} reason={result.approval_reason}"
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-9405"]
    approved = next(e for e in events if e["event_type"] == "InvoiceApproved")
    assert approved["payload"].get("reflected") is True


def test_uat_compound_4_6_sql_injection_vendor(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-COMP-46.txt",
        """
        Invoice Number: INV-9406
        Vendor: '; DROP TABLE inventory; --
        Item: WidgetA
        Qty: 1
        Unit Price: $250
        Total: $250
        """,
    )
    assert result.status == "paid"
