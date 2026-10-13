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
            "paid",  # W-A → WidgetA soft escalate; stub VP approves
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
    pipe = Pipeline(work_dir=pipe_dir, use_grok=False, profile="case", soft_price_bands=False)
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

    # --- 5. User journey (1.9.0): HITL, guardrails, revision, twin ---------------


HV_HITL_BODY = """
Invoice Number: {inv}
Vendor: Big Co
Item: WidgetA
Qty: 10
Unit Price: $250
Item: WidgetB
Qty: 8
Unit Price: $500
Item: GadgetX
Qty: 5
Unit Price: $750
Total: $10250
"""

ALIAS_BODY = """
Invoice Number: {inv}
Vendor: Alias Traders
Item: Widget Alpha
Qty: 1
Unit Price: $250
Total: $250
"""

DATA = Path(__file__).resolve().parents[1] / "data" / "invoices"


def _run_gate(tmp: Path, name: str, body: str, gate):
    path = _write(tmp, name, body)
    pipe = Pipeline(work_dir=tmp / f"run_{name}", use_grok=False, profile="case", human_gate=gate)
    return pipe, pipe.process_file(path)


def _gate_event(pipe: Pipeline) -> dict:
    return next(e for e in pipe.events.read_all() if e["event_type"] == "HumanApprovalGate")


@pytest.mark.parametrize(
    ("tc_id", "body", "action", "expect"),
    [
        ("TC-HITL-01", HV_HITL_BODY.format(inv="INV-9501"), "approve", "paid"),
        ("TC-HITL-02", HV_HITL_BODY.format(inv="INV-9502"), "reject", "rejected"),
        ("TC-HITL-03", HV_HITL_BODY.format(inv="INV-9503"), "escalate", "paid"),
        ("TC-HITL-04", ALIAS_BODY.format(inv="INV-9504"), "approve", "paid"),
        ("TC-HITL-05", ALIAS_BODY.format(inv="INV-9505"), "reject", "rejected"),
        ("TC-HITL-06", ALIAS_BODY.format(inv="INV-9506"), "escalate", "paid"),
    ],
)
def test_uat_hitl_actions(tmp_path: Path, tc_id: str, body: str, action: str, expect: str) -> None:
    pipe, result = _run_gate(tmp_path, f"{tc_id}.txt", body, lambda _inv: action)
    assert result.status == expect, f"{tc_id}: {result.status} issues={result.issues}"
    assert _gate_event(pipe)["payload"]["action"] == action
    approved = [e for e in pipe.events.read_all() if e["event_type"] == "InvoiceApproved"]
    if action == "approve":
        assert approved[0]["payload"]["actor"] == "human_cli"
        assert approved[0]["payload"]["human"] is True
    if action == "reject":
        assert not approved
        assert "Human rejected" in (result.approval_reason or "")
    if action == "escalate":
        assert approved[0]["payload"]["reflected"] is True
        assert approved[0]["payload"]["human"] is False


def test_uat_hitl_07_gate_skipped_when_no_scrutiny(tmp_path: Path) -> None:
    def _boom(_inv):
        raise AssertionError("gate must not run for clean low-value invoice")

    _pipe, result = _run_gate(
        tmp_path,
        "TC-HITL-07.txt",
        """
        Invoice Number: INV-9507
        Vendor: Delta Corp
        Item: WidgetA
        Qty: 5
        Unit Price: $250
        Total: $1250
        """,
        _boom,
    )
    assert result.status == "paid"


def test_uat_hitl_08_gate_skipped_on_hard_reject(tmp_path: Path) -> None:
    def _boom(_inv):
        raise AssertionError("gate must not run when validation rejects")

    # High value plus overstock: stock check fails before any human or VP gate.
    _pipe, result = _run_gate(
        tmp_path,
        "TC-HITL-08.txt",
        """
        Invoice Number: INV-9508
        Vendor: Maxi-Corp
        Item: WidgetB
        Qty: 25
        Unit Price: $500
        Total: $12500
        """,
        _boom,
    )
    assert result.status == "rejected"
    assert any("insufficient_stock" in i for i in result.issues)


def test_uat_guard_01_digit_sku_rejects(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "TC-GUARD-01.txt",
        """
        Invoice Number: INV-9511
        Vendor: SupplyCo
        Item: Widg3tA
        Qty: 3
        Unit Price: $250
        Total: $750
        """,
    )
    assert result.status == "rejected"
    assert any("unknown_item" in i for i in result.issues)


@pytest.mark.parametrize(
    ("tc_id", "qty"),
    [("TC-GUARD-02", "~5"), ("TC-GUARD-03", "5.0000001")],
)
def test_uat_guard_qty_fail_closed(tmp_path: Path, tc_id: str, qty: str) -> None:
    path = _write(
        tmp_path,
        f"{tc_id}.txt",
        f"""
        Invoice Number: INV-{tc_id[-2:]}00
        Vendor: Approx Co
        Item: GadgetX
        Qty: {qty}
        Unit Price: $100
        Total: $500
        """,
    )
    pipe = Pipeline(work_dir=tmp_path / f"run_{tc_id}", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status == "failed", f"{tc_id}: {result.status}"
    failed = [e for e in pipe.events.read_all() if e["event_type"] == "IngestionFailed"]
    assert failed and "invalid_quantity" in failed[0]["payload"]["error"]
    assert pipe.inventory.stock_levels()["GadgetX"] == 5  # fail closed: no draw


def test_uat_guard_04_widget_alpha_soft_vp(tmp_path: Path) -> None:
    path = _write(tmp_path, "TC-GUARD-04.txt", ALIAS_BODY.format(inv="INV-9514"))
    pipe = Pipeline(work_dir=tmp_path / "run_g04", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status == "paid"
    events = pipe.events.read_all()
    validated = next(e for e in events if e["event_type"] == "InvoiceValidated")
    soft = validated["payload"].get("soft_escalations") or []
    assert any("Widget Alpha" in str(s) and "WidgetA" in str(s) for s in soft)
    approved = next(e for e in events if e["event_type"] == "InvoiceApproved")
    assert approved["payload"]["reflected"] is True
    assert approved["payload"]["actor"] == "vp_agent"


def test_uat_guard_05_vendor_injection_review_then_pay(tmp_path: Path) -> None:
    from invoice_automation.policy.invariants import VENDOR_INJECTION_REVIEW_PREFIX

    path = _write(
        tmp_path,
        "TC-GUARD-05.txt",
        """
        Invoice Number: INV-9515
        Vendor: '; DROP TABLE inventory; --
        Item: WidgetA
        Qty: 1
        Unit Price: $250
        Total: $250
        """,
    )
    pipe = Pipeline(work_dir=tmp_path / "run_g05", use_grok=False, profile="case")
    result = pipe.process_file(path)
    assert result.status == "paid"
    events = pipe.events.read_all()
    validated = next(e for e in events if e["event_type"] == "InvoiceValidated")
    soft = validated["payload"].get("soft_escalations") or []
    assert any(str(s).startswith(VENDOR_INJECTION_REVIEW_PREFIX) for s in soft)
    approved = next(e for e in events if e["event_type"] == "InvoiceApproved")
    assert approved["payload"]["actor"] == "vp_agent"
    assert pipe.inventory.stock_levels()["WidgetA"] == 14  # DB intact, one unit drawn


def _tight_widget_a_pipe(tmp: Path) -> Pipeline:
    """Leave WidgetA at 1 after a prior paid WidgetA×3 for INV-QTY."""
    from decimal import Decimal

    from invoice_automation.domain.models import LineItem

    pipe = Pipeline(work_dir=tmp / "rt", use_grok=False, profile="case")
    pipe.inventory.decrement_stock([LineItem("WidgetA", 11, Decimal("250"))])
    paid = pipe.saga.pay(
        invoice_id="INV-QTY",
        vendor="Precision Parts Ltd.",
        amount=Decimal("810"),
        correlation_id="c-first",
        items=(LineItem("WidgetA", 3, Decimal("250")),),
    )
    assert paid.status == "success"
    assert pipe.inventory.stock_levels()["WidgetA"] == 1
    return pipe


def _revision_file(tmp: Path, qty: int) -> Path:
    import json

    path = tmp / f"inv_qty_rev_{qty}.json"
    path.write_text(
        json.dumps(
            {
                "invoice_number": "INV-QTY",
                "vendor": {"name": "Precision Parts Ltd."},
                "date": "2026-01-22",
                "due_date": "2026-02-22",
                "line_items": [{"item": "WidgetA", "quantity": qty, "unit_price": 250.00}],
                "subtotal": 250.00 * qty,
                "tax_rate": 0.08,
                "tax_amount": 20.00 * qty,
                "total": 270.00 * qty,
                "currency": "USD",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_uat_rev_01_delta_stock_under_tight_stock(tmp_path: Path) -> None:
    """WidgetA 3→4 needs only +1 on the shelf; prior_items credit the first draw."""
    pipe = _tight_widget_a_pipe(tmp_path)
    result = pipe.process_file(_revision_file(tmp_path, 4))
    assert result.status == "paid", f"issues={result.issues}"
    assert pipe.inventory.stock_levels()["WidgetA"] == 0
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-QTY"]
    assert any(e["event_type"] == "PaymentRevised" for e in events)


def test_uat_rev_02_delta_beyond_shelf_rejects(tmp_path: Path) -> None:
    """WidgetA 3→5 needs +2 but one is left: reject and keep stock."""
    pipe = _tight_widget_a_pipe(tmp_path)
    result = pipe.process_file(_revision_file(tmp_path, 5))
    assert result.status == "rejected"
    assert any("insufficient_stock" in i for i in result.issues)
    assert pipe.inventory.stock_levels()["WidgetA"] == 1


def test_uat_twin_01_format_twin_no_second_draw(tmp_path: Path) -> None:
    import sqlite3

    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    first = pipe.process_file(DATA / "invoice_1011.txt")
    stock_after_first = pipe.inventory.stock_levels()
    second = pipe.process_file(DATA / "invoice_1011.pdf")
    assert (first.status, second.status) == ("paid", "paid")
    assert pipe.inventory.stock_levels() == stock_after_first
    with sqlite3.connect(tmp_path / "rt" / "system.db") as conn:
        rows = conn.execute(
            "SELECT status FROM payment_intent WHERE invoice_id='INV-1011'"
        ).fetchall()
    assert rows == [("SUCCEEDED",)]


def _db_rows(tmp: Path, sql: str, args: tuple = ()) -> list:
    import sqlite3

    with sqlite3.connect(tmp / "rt" / "system.db") as conn:
        return conn.execute(sql, args).fetchall()


def test_uat_recon_01_gateway_ok_stock_fail_holds_permit(tmp_path: Path) -> None:
    """Gateway pays, stock draw fails: RECONCILE, intent held, permit not consumed."""
    from invoice_automation.domain.exceptions import ValidationError

    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")

    def _fail(_items):
        raise ValidationError("insufficient_stock:GadgetX")

    pipe.inventory.decrement_stock = _fail  # type: ignore[method-assign]
    path = _write(
        tmp_path,
        "TC-RECON-01.txt",
        """
        Invoice Number: INV-9601
        Vendor: Recon Co
        Item: GadgetX
        Qty: 1
        Unit Price: $100
        Total: $100
        """,
    )
    result = pipe.process_file(path)
    assert result.status == "reconcile", f"issues={result.issues} reason={result.approval_reason}"
    types = [e["event_type"] for e in pipe.events.read_all() if e.get("invoice_id") == "INV-9601"]
    assert "PaymentStockReconcile" in types
    assert "PaymentSucceeded" not in types
    assert _db_rows(tmp_path, "SELECT COUNT(*) FROM consumed_permits") == [(0,)]
    assert _db_rows(
        tmp_path,
        "SELECT status, needs_manual_reconciliation FROM payment_intent WHERE invoice_id=?",
        ("INV-9601",),
    ) == [("RECONCILE", 1)]
    assert [r["invoice_id"] for r in pipe.saga.list_reconcile_intents()] == ["INV-9601"]
    assert pipe.inventory.stock_levels()["GadgetX"] == 5  # no draw happened


def test_uat_case_rev_01_real_1004_revision_delta_stock(tmp_path: Path) -> None:
    """invoice_1004 then its R1 revision: only the added GadgetX×5 draws stock."""
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    start = pipe.inventory.stock_levels()
    first = pipe.process_file(DATA / "invoice_1004.json")
    assert first.status == "paid", f"issues={first.issues}"
    after_first = pipe.inventory.stock_levels()
    assert after_first["WidgetA"] == start["WidgetA"] - 3
    assert after_first["WidgetB"] == start["WidgetB"] - 2
    assert after_first["GadgetX"] == start["GadgetX"]

    second = pipe.process_file(DATA / "invoice_1004_revised.json")
    assert second.status == "paid", f"issues={second.issues} reason={second.approval_reason}"
    after_second = pipe.inventory.stock_levels()
    assert after_second["WidgetA"] == after_first["WidgetA"]  # no second draw
    assert after_second["WidgetB"] == after_first["WidgetB"]
    assert after_second["GadgetX"] == start["GadgetX"] - 5  # only the delta
    events = [e for e in pipe.events.read_all() if e.get("invoice_id") == "INV-1004"]
    assert any(e["event_type"] == "PaymentRevised" for e in events)
    assert _db_rows(
        tmp_path, "SELECT status FROM payment_intent WHERE invoice_id=?", ("INV-1004",)
    ) == [("SUCCEEDED",)]


def test_uat_case_twin_01_real_1011_txt_then_pdf(tmp_path: Path) -> None:
    """invoice_1011 txt then pdf on one Pipeline: both paid, one intent, one draw."""
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="case")
    start = pipe.inventory.stock_levels()
    first = pipe.process_file(DATA / "invoice_1011.txt")
    after_first = pipe.inventory.stock_levels()
    second = pipe.process_file(DATA / "invoice_1011.pdf")
    assert (first.status, second.status) == ("paid", "paid")
    assert after_first != start  # first file drew stock
    assert pipe.inventory.stock_levels() == after_first  # twin did not draw again
    assert _db_rows(
        tmp_path, "SELECT status FROM payment_intent WHERE invoice_id=?", ("INV-1011",)
    ) == [("SUCCEEDED",)]
    paid = [
        e
        for e in pipe.events.read_all()
        if e.get("invoice_id") == "INV-1011"
        and e["event_type"] in {"PaymentSucceeded", "PaymentRevised"}
    ]
    assert not any(e["payload"].get("revision") for e in paid)


def test_uat_prod_01_absurd_unit_price_not_paid(tmp_path: Path) -> None:
    """Profile=prod: a 10x catalog unit price must not pay silently."""
    path = _write(
        tmp_path,
        "TC-PROD-01.txt",
        """
        Invoice Number: INV-9701
        Vendor: Gouge Co
        Item: WidgetA
        Qty: 1
        Unit Price: $2500
        Total: $2500
        """,
    )
    pipe = Pipeline(work_dir=tmp_path / "rt", use_grok=False, profile="prod")
    result = pipe.process_file(path)
    assert result.status != "paid", f"silent pay: {result.status}"
    blob = " ".join(result.issues) + " " + (result.approval_reason or "")
    assert "price_mismatch" in blob
    assert pipe.inventory.stock_levels()["WidgetA"] == 15
