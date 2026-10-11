"""Server-side aggregates for the Tableau-style AP dashboard."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from invoice_automation.adapters.workbench_store import WorkbenchRecord


def is_exception(record: WorkbenchRecord) -> bool:
    return bool(
        record.issues
        or record.needs_override
        or record.hard_blocked
        or record.status == "needs_override"
    )


def stage_n(record: WorkbenchRecord) -> int:
    """Map workbench status to pipeline stage 1–4 (ingest→validate→approve→pay)."""
    if record.status in {"paid", "rejected"}:
        return 4
    if record.status == "awaiting_vp" or record.escalated or record.high_value:
        return 3
    # Captured + validated (or held on findings) — analyst workbench
    return 2


def risk_level(record: WorkbenchRecord) -> str:
    """Return high | medium | low for conditional formatting."""
    if record.hard_blocked or any(
        i.startswith(("negative_amount", "invalid_quantity", "zero_stock")) for i in record.issues
    ):
        return "high"
    if record.high_value or record.issues or record.needs_override:
        return "medium"
    return "low"


def short_findings(record: WorkbenchRecord, limit: int = 2) -> str:
    if not record.issues:
        return "—"
    codes = []
    for issue in record.issues[:limit]:
        codes.append(issue.split(":")[0].replace("_", " "))
    extra = len(record.issues) - limit
    text = ", ".join(codes)
    if extra > 0:
        text += f" +{extra}"
    return text


def enrich(record: WorkbenchRecord) -> dict[str, Any]:
    """Row dict for dense tables / watchlist."""
    return {
        "record": record,
        "stage": stage_n(record),
        "risk": risk_level(record),
        "findings": short_findings(record),
        "amount_f": float(record.amount),
        "conf_pct": int(round(record.confidence * 100)),
    }


def build_dashboard(rows: list[WorkbenchRecord]) -> dict[str, Any]:
    """Full home-dashboard payload."""
    open_rows = [r for r in rows if r.status not in {"paid", "rejected"}]
    exceptions = [r for r in open_rows if is_exception(r)]
    vp = [r for r in open_rows if r.status == "awaiting_vp" or r.escalated or r.high_value]
    paid = [r for r in rows if r.status == "paid"]
    rejected = [r for r in rows if r.status == "rejected"]
    clear_ready = [r for r in open_rows if not is_exception(r) and r.id not in {v.id for v in vp}]

    funnel = [
        {"key": "captured", "label": "1 Captured", "count": len(rows), "href": "/capture"},
        {
            "key": "exceptions",
            "label": "2 Exceptions",
            "count": len(exceptions),
            "href": "/exceptions",
        },
        {
            "key": "awaiting_vp",
            "label": "3 Awaiting VP",
            "count": len(vp),
            "href": "/approvals",
        },
        {
            "key": "paid",
            "label": "4 Paid",
            "count": len(paid),
            "href": "/audit?status=paid",
        },
    ]
    max_funnel = max((f["count"] for f in funnel), default=1) or 1
    for f in funnel:
        f["pct"] = int(100 * f["count"] / max_funnel)

    # Vendor exposure ($ open)
    vendor_map: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in open_rows:
        vendor_map[r.vendor or "Unknown"] += r.amount
    vendor_exposure = sorted(
        [
            {"vendor": v, "amount": float(a), "label": f"${float(a):,.0f}"}
            for v, a in vendor_map.items()
        ],
        key=lambda x: x["amount"],
        reverse=True,
    )[:8]
    max_vendor = max((v["amount"] for v in vendor_exposure), default=1) or 1.0
    for v in vendor_exposure:
        v["pct"] = int(100 * v["amount"] / max_vendor)

    # Issue mix
    buckets = {"unknown SKU": 0, "stock": 0, "amount/qty": 0, "other": 0, "clean": 0}
    for r in open_rows:
        if not r.issues:
            buckets["clean"] += 1
            continue
        tagged = False
        for issue in r.issues:
            if issue.startswith("unknown_item"):
                buckets["unknown SKU"] += 1
                tagged = True
                break
            if "stock" in issue:
                buckets["stock"] += 1
                tagged = True
                break
            if issue.startswith(("negative_amount", "invalid_quantity", "missing_")):
                buckets["amount/qty"] += 1
                tagged = True
                break
        if not tagged:
            buckets["other"] += 1
    issue_mix = [{"label": k, "count": c} for k, c in buckets.items() if c > 0]

    # Confidence × amount points for scatter
    scatter = [
        {
            "x": float(r.amount),
            "y": round(r.confidence * 100, 1),
            "id": r.invoice_id,
            "href": f"/invoices/{r.id}",
            "risk": risk_level(r),
        }
        for r in open_rows
    ]

    # Watchlist: open invoices ranked by risk then amount
    risk_rank = {"high": 0, "medium": 1, "low": 2}
    watch_sorted = sorted(
        open_rows,
        key=lambda r: (risk_rank[risk_level(r)], -float(r.amount)),
    )
    watchlist = [enrich(r) for r in watch_sorted[:10]]

    def _sum(rs: list[WorkbenchRecord]) -> float:
        return float(sum((r.amount for r in rs), Decimal("0")))

    open_dollars = _sum(open_rows)
    exception_dollars = _sum(exceptions)
    hard_blocked = [r for r in open_rows if r.hard_blocked]
    blocked_dollars = _sum(hard_blocked)
    # Idle STP: clean, under policy threshold, analyst can pay now — cash sitting unused.
    idle_stp = [r for r in clear_ready if r.amount <= Decimal("10000") and r.amount > 0]
    idle_stp_dollars = _sum(idle_stp)
    policy_hold = [r for r in vp if r.amount > 0]
    policy_hold_dollars = _sum(policy_hold)

    # STP eligibility: share of volume that needs no exception work and no VP policy hold.
    stp_eligible = [
        r
        for r in rows
        if not is_exception(r) and not (r.high_value or r.escalated) and r.amount > 0
    ]
    stp_rate = (100.0 * len(stp_eligible) / len(rows)) if rows else 0.0
    exception_rate = (100.0 * len(exceptions) / len(open_rows)) if open_rows else 0.0

    ages = [r.age_hours for r in exceptions] or [0.0]
    ages_sorted = sorted(ages)
    mid = len(ages_sorted) // 2
    median_exception_age = (
        ages_sorted[mid] if len(ages_sorted) % 2 else (ages_sorted[mid - 1] + ages_sorted[mid]) / 2
    )
    oldest_exception_age = max(ages) if ages else 0.0

    paid_dollars = _sum(paid)
    total_volume = _sum(rows) or 1.0
    touchless_paid = [r for r in paid if not r.issues and not r.hard_blocked and not r.high_value]
    # Realized STP among closed work (paid+rejected): paid clean low-value / closed.
    closed = paid + rejected
    realized_stp = 100.0 * len(touchless_paid) / len(closed) if closed else 0.0

    return {
        "kpis": {
            # Outcome metrics (primary cards)
            "open_dollars": open_dollars,
            "open_count": len(open_rows),
            "exception_dollars": exception_dollars,
            "exception_count": len(exceptions),
            "exception_rate": round(exception_rate, 1),
            "blocked_dollars": blocked_dollars,
            "blocked_count": len(hard_blocked),
            "idle_stp_dollars": idle_stp_dollars,
            "idle_stp_count": len(idle_stp),
            "policy_hold_dollars": policy_hold_dollars,
            "policy_hold_count": len(policy_hold),
            "stp_rate": round(stp_rate, 1),
            "realized_stp": round(realized_stp, 1),
            "median_exception_age_h": round(median_exception_age, 2),
            "oldest_exception_age_h": round(oldest_exception_age, 2),
            "paid_dollars": paid_dollars,
            "paid_count": len(paid),
            "rejected_count": len(rejected),
            "captured": len(rows),
            "volume_dollars": float(total_volume) if rows else 0.0,
            # Kept for any legacy template refs
            "exceptions": len(exceptions),
            "awaiting_vp": len(vp),
            "paid": len(paid),
            "clear_ready": len(clear_ready),
            "open": len(open_rows),
        },
        "funnel": funnel,
        "vendor_exposure": vendor_exposure,
        "issue_mix": issue_mix,
        "scatter": scatter,
        "watchlist": watchlist,
        "chart_json": {
            "funnel": funnel,
            "vendors": vendor_exposure,
            "issues": issue_mix,
            "scatter": scatter,
        },
    }


def filter_rows(
    rows: list[WorkbenchRecord],
    *,
    q: str = "",
    status: str = "",
    high_value: str = "",
    findings: str = "",
    amount_band: str = "",
) -> list[WorkbenchRecord]:
    """Apply work-queue filter shelf query params."""
    out = list(rows)
    if q.strip():
        needle = q.strip().lower()
        out = [r for r in out if needle in r.vendor.lower() or needle in r.invoice_id.lower()]
    if status:
        out = [r for r in out if r.status == status]
    if high_value == "1":
        out = [r for r in out if r.high_value]
    if findings == "1":
        out = [r for r in out if r.issues]
    elif findings == "0":
        out = [r for r in out if not r.issues]
    if amount_band == "under10k":
        out = [r for r in out if r.amount <= Decimal("10000")]
    elif amount_band == "over10k":
        out = [r for r in out if r.amount > Decimal("10000")]
    return out
