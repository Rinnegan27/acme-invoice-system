"""Galatiq AP Control Centre — Tableau-style FastAPI workbench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from invoice_automation.auth import (
    MockOidcIdp,
    SessionClaims,
    issue_session_cookie,
    verify_session_cookie,
)
from invoice_automation.auth.session import COOKIE_NAME
from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.sim.runner import SimReport, run_case_simulation
from web.analytics import (
    build_dashboard,
    enrich,
    filter_rows,
    is_exception,
    risk_level,
    stage_n,
)
from web.deps import (
    DATA_DIR,
    SIM_DIR,
    SIM_REPORT_PATH,
    UPLOAD_DIR,
    get_service,
    sample_paths,
    service_from_cookie,
)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Galatiq AP Control Centre")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

_IDP = MockOidcIdp()


def _claims(request: Request) -> SessionClaims | None:
    """Return verified session claims, or None when missing/invalid."""
    return verify_session_cookie(request.cookies.get(COOKIE_NAME))


def _session(request: Request) -> tuple[str, str]:
    """Role and LLM from a verified HMAC session only (no unsigned role cookie)."""
    claims = _claims(request)
    if claims is None:
        # Legacy unsigned cookies are ignored. Default to analyst/stub for browse.
        return "analyst", "stub"
    return claims.role, claims.llm


def _actor(request: Request) -> str:
    claims = _claims(request)
    return claims.actor if claims is not None else "analyst"


def _require_session(request: Request) -> SessionClaims | RedirectResponse:
    """Mutations require a verified session cookie."""
    claims = _claims(request)
    if claims is None:
        return _redirect(
            "/login",
            flash_kind="err",
            flash_msg="Sign in required. Use the mock IdP login (signed session).",
        )
    return claims


def _flash(request: Request) -> dict[str, str] | None:
    kind = request.cookies.get("flash_kind")
    message = request.cookies.get("flash_msg")
    if kind and message:
        return {"kind": kind, "message": message}
    return None


def _redirect(url: str, *, flash_kind: str = "", flash_msg: str = "") -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if flash_kind and flash_msg:
        resp.set_cookie("flash_kind", flash_kind, max_age=8)
        resp.set_cookie("flash_msg", quote(flash_msg, safe=""), max_age=8)
    else:
        resp.delete_cookie("flash_kind")
        resp.delete_cookie("flash_msg")
    return resp


def _ctx(request: Request, nav: str, **extra: Any) -> dict[str, Any]:
    role, llm = _session(request)
    claims = _claims(request)
    flash = _flash(request)
    if flash and flash.get("message"):
        from urllib.parse import unquote

        flash["message"] = unquote(flash["message"])
    return {
        "request": request,
        "nav": nav,
        "role": role,
        "llm": llm,
        "actor": claims.actor if claims else role,
        "signed_in": claims is not None,
        "flash": flash,
        **extra,
    }


def _svc(request: Request):
    _, llm = _session(request)
    return service_from_cookie(llm)


def _filters(request: Request) -> dict[str, str]:
    return {
        "q": request.query_params.get("q", ""),
        "status": request.query_params.get("status", ""),
        "high_value": request.query_params.get("high_value", ""),
        "findings": request.query_params.get("findings", ""),
        "amount_band": request.query_params.get("amount_band", ""),
    }


def _stage_meta(record) -> dict[str, Any]:
    current = stage_n(record)
    names = ["Ingestion", "Validation", "Approval", "Payment"]
    steps = []
    for i, name in enumerate(names, start=1):
        steps.append(
            {
                "n": i,
                "name": name,
                "done": i < current or (current == 4 and record.status in {"paid", "rejected"}),
                "current": i == current,
            }
        )
    if record.status == "paid":
        for s in steps:
            s["done"] = True
            s["current"] = s["n"] == 4
    return {"steps": steps, "current": current, "risk": risk_level(record)}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(request, "login", users=_IDP.list_users(), idp_issuer=_IDP.issuer),
    )


@app.post("/login")
async def login(
    username: str = Form(...),
    llm: str = Form("stub"),
) -> RedirectResponse:
    token = _IDP.authenticate(username)
    if token is None:
        return _redirect("/login", flash_kind="err", flash_msg="Unknown mock IdP user.")
    llm = llm if llm in {"stub", "grok"} else "stub"
    cookie = issue_session_cookie(role=token.role, llm=llm, sub=token.sub)
    dest = "/approvals" if token.role == "vp" else "/exceptions"
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(COOKIE_NAME, cookie, httponly=True, samesite="lax")
    # Clear legacy unsigned cookies if present.
    resp.delete_cookie("galatiq_role")
    resp.delete_cookie("galatiq_llm")
    get_service.cache_clear()
    return resp


@app.post("/session")
async def set_session(role: str = Form("analyst"), llm: str = Form("stub")) -> RedirectResponse:
    """Role switch via mock IdP demo users (issues a new signed session)."""
    role = role if role in {"analyst", "vp"} else "analyst"
    username = "vp@acme.local" if role == "vp" else "analyst@acme.local"
    token = _IDP.authenticate(username)
    assert token is not None
    llm = llm if llm in {"stub", "grok"} else "stub"
    cookie = issue_session_cookie(role=token.role, llm=llm, sub=token.sub)
    dest = "/approvals" if role == "vp" else "/exceptions"
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(COOKIE_NAME, cookie, httponly=True, samesite="lax")
    resp.delete_cookie("galatiq_role")
    resp.delete_cookie("galatiq_llm")
    get_service.cache_clear()
    return resp


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    svc = _svc(request)
    role, _ = _session(request)
    dash = build_dashboard(svc.list_all())
    # Analysts see the VP count but cannot drill into the VP desk.
    if role != "vp":
        for item in dash["funnel"]:
            if item.get("key") == "awaiting_vp":
                item["href"] = None
        dash["chart_json"]["funnel"] = dash["funnel"]
    return templates.TemplateResponse(
        request,
        "home.html",
        _ctx(
            request,
            "home",
            dash=dash,
            chart_json_str=json.dumps(dash["chart_json"]),
        ),
    )


@app.get("/sim", response_class=HTMLResponse)
async def sim_page(request: Request) -> HTMLResponse:
    """Standalone Case Lab — not linked from the AP Control Centre nav."""
    report = SimReport.load(SIM_REPORT_PATH)
    chart = {"labels": [], "fail_by_stage": {}, "terminal_by_stage": {}}
    if report is not None:
        payload = report.to_dict()
        chart = payload.get("chart_json") or {
            "labels": ["1 Ingestion", "2 Validation", "3 Approval", "4 Payment"],
            "fail_by_stage": report.fail_by_stage,
            "terminal_by_stage": report.terminal_by_stage,
        }
    return templates.TemplateResponse(
        request,
        "sim.html",
        _ctx(
            request,
            "sim",
            report=report,
            chart_json_str=json.dumps(chart),
        ),
    )


@app.post("/sim/run")
async def sim_run(request: Request) -> RedirectResponse:
    _, llm = _session(request)
    use_grok = llm == "grok"
    report = run_case_simulation(
        SIM_DIR / "wb",
        data_dir=DATA_DIR,
        use_grok=use_grok,
        reset_work_dir=True,
    )
    report.save(SIM_REPORT_PATH)
    kind = "ok" if report.ok else "err"
    msg = f"Case simulation: {report.passed}/{report.total} passed."
    return _redirect("/sim", flash_kind=kind, flash_msg=msg)


@app.get("/capture", response_class=HTMLResponse)
async def capture(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "capture.html",
        _ctx(request, "capture", sample_count=len(sample_paths())),
    )


@app.post("/capture/upload")
async def capture_upload(request: Request, files: list[UploadFile] = File(...)) -> RedirectResponse:
    svc = _svc(request)
    role, _ = _session(request)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    errors: list[str] = []
    for f in files:
        path = UPLOAD_DIR / (f.filename or "upload.bin")
        path.write_bytes(await f.read())
        try:
            svc.ingest_file(path, actor_role=role)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")
    msg = f"Captured {ok} invoice(s)."
    if errors:
        msg += " Failures: " + "; ".join(errors[:3])
    return _redirect("/", flash_kind="ok" if ok else "err", flash_msg=msg)


@app.post("/capture/samples")
async def capture_samples(request: Request) -> RedirectResponse:
    svc = _svc(request)
    role, _ = _session(request)
    ok, errors = svc.ingest_many(sample_paths(), actor_role=role)
    msg = f"Processed {len(ok)} sample invoices."
    if errors:
        msg += " Some failed: " + "; ".join(errors[:3])
    return _redirect("/", flash_kind="ok", flash_msg=msg)


@app.post("/capture/reset")
async def capture_reset(request: Request) -> RedirectResponse:
    svc = _svc(request)
    svc.reset()
    get_service.cache_clear()
    return _redirect(
        "/capture",
        flash_kind="ok",
        flash_msg="Workbench cleared. Process samples again for a clean list.",
    )


def _list_page(
    request: Request,
    *,
    nav: str,
    page_title: str,
    page_lead: str,
    empty_text: str,
    rows: list,
    show_status_filter: bool = False,
    status_options: list[str] | None = None,
    stats: dict[str, int] | None = None,
    show_vp_bulk: bool = False,
) -> HTMLResponse:
    filters = _filters(request)
    filtered = filter_rows(
        rows,
        q=filters["q"],
        status=filters["status"],
        high_value=filters["high_value"],
        findings=filters["findings"],
        amount_band=filters["amount_band"],
    )
    return templates.TemplateResponse(
        request,
        "list.html",
        _ctx(
            request,
            nav,
            page_title=page_title,
            page_lead=page_lead,
            empty_text=empty_text,
            rows=filtered,
            enriched=[enrich(r) for r in filtered],
            filters=filters,
            show_status_filter=show_status_filter,
            status_options=status_options or [],
            stats=stats or {},
            show_vp_bulk=show_vp_bulk,
        ),
    )


@app.get("/exceptions", response_class=HTMLResponse)
async def exceptions(request: Request) -> HTMLResponse:
    svc = _svc(request)
    filters = _filters(request)
    # Default: true exceptions. findings=0 → idle STP queue (clean ≤ policy, analyst-payable).
    if filters["findings"] == "0":
        rows = [
            r
            for r in svc.list_inbox()
            if not is_exception(r) and not r.high_value and not r.escalated
        ]
        title = "Ready to pay"
        lead = "Clean invoices under policy — straight-through candidates waiting on analyst pay."
        empty = "No idle STP invoices. Everything clean is already paid or in VP hold."
    else:
        rows = svc.list_exceptions()
        title = "Exceptions"
        lead = "Inventory and extract findings that block straight-through pay."
        empty = "No open exceptions. Capture invoices or clear filters."
    return _list_page(
        request,
        nav="exceptions",
        page_title=title,
        page_lead=lead,
        empty_text=empty,
        rows=rows,
        show_status_filter=True,
        status_options=["pending_review", "needs_override", "awaiting_vp"],
    )


@app.get("/approvals", response_class=HTMLResponse)
async def approvals(request: Request) -> HTMLResponse:
    role, _ = _session(request)
    if role != "vp":
        return _redirect(
            "/exceptions",
            flash_kind="err",
            flash_msg="Approvals is the VP desk. Switch Working as → VP Approver.",
        )
    svc = _svc(request)
    rows = svc.list_vp_queue()
    return _list_page(
        request,
        nav="approvals",
        page_title="Approvals",
        page_lead="VP desk — high-value and escalated invoices only.",
        empty_text="Approvals queue is clear.",
        rows=rows,
        show_status_filter=True,
        status_options=["awaiting_vp", "pending_review", "needs_override"],
        stats={
            "total": len(rows),
            "hv": sum(1 for r in rows if r.high_value),
            "esc": sum(1 for r in rows if r.escalated),
            "blk": sum(1 for r in rows if r.hard_blocked),
            "payable": sum(1 for r in rows if not r.hard_blocked),
        },
        show_vp_bulk=True,
    )


@app.post("/approvals/approve-all")
async def approvals_approve_all(request: Request) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "vp":
        return _redirect(
            "/exceptions",
            flash_kind="err",
            flash_msg="Only VP Approver can bulk-approve.",
        )
    svc = _svc(request)
    approved, skipped, errors = svc.vp_approve_all(actor=claims.actor)
    msg = f"Approved & paid {approved} invoice(s)."
    if skipped:
        msg += f" Skipped {skipped} hard-blocked or failed."
    if errors:
        msg += " " + "; ".join(errors[:2])
    return _redirect(
        "/approvals" if skipped or errors else "/audit",
        flash_kind="ok" if approved else "err",
        flash_msg=msg,
    )


@app.post("/approvals/reject-all")
async def approvals_reject_all(request: Request) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "vp":
        return _redirect(
            "/exceptions",
            flash_kind="err",
            flash_msg="Only VP Approver can bulk-reject.",
        )
    svc = _svc(request)
    rejected, errors = svc.vp_reject_all(actor=claims.actor)
    msg = f"Rejected {rejected} invoice(s)."
    if errors:
        msg += " " + "; ".join(errors[:2])
    return _redirect(
        "/audit" if rejected and not errors else "/approvals",
        flash_kind="ok" if rejected else "err",
        flash_msg=msg,
    )


@app.get("/audit", response_class=HTMLResponse)
async def audit(request: Request) -> HTMLResponse:
    svc = _svc(request)
    return _list_page(
        request,
        nav="audit",
        page_title="Audit",
        page_lead="Terminal ledger — paid and rejected with reconstructable decisions.",
        empty_text="No payments or declines recorded yet.",
        rows=svc.list_history(),
        show_status_filter=True,
        status_options=["paid", "rejected"],
    )


@app.get("/reconcile", response_class=HTMLResponse)
async def reconcile(request: Request) -> HTMLResponse:
    svc = _svc(request)
    return templates.TemplateResponse(
        request,
        "reconcile.html",
        _ctx(request, "reconcile", rows=svc.list_reconcile()),
    )


@app.post("/reconcile/{invoice_id}/retry")
async def reconcile_retry(request: Request, invoice_id: str) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    svc = _svc(request)
    try:
        result = svc.retry_reconcile_stock(invoice_id, actor_role=claims.actor)
        return _redirect(
            "/reconcile",
            flash_kind="ok",
            flash_msg=f"Stock retry ok for {result['invoice_id']}.",
        )
    except ValidationError as exc:
        return _redirect("/reconcile", flash_kind="err", flash_msg=str(exc))


@app.post("/reconcile/{invoice_id}/ack")
async def reconcile_ack(
    request: Request,
    invoice_id: str,
    note: str = Form(""),
) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    svc = _svc(request)
    try:
        svc.acknowledge_reconcile(invoice_id, note=note, actor_role=claims.actor)
        return _redirect(
            "/reconcile",
            flash_kind="ok",
            flash_msg=f"Reconcile acked for {invoice_id}.",
        )
    except ValidationError as exc:
        return _redirect("/reconcile", flash_kind="err", flash_msg=str(exc))


@app.get("/invoices/{record_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, record_id: int) -> HTMLResponse:
    svc = _svc(request)
    role, _ = _session(request)
    record = svc.get(record_id)
    if record is None:
        return _redirect("/exceptions", flash_kind="err", flash_msg="Invoice not found")
    events = svc.store.events_for(record.correlation_id)
    if record.status in {"paid", "rejected"}:
        back = "/audit"
        nav = "audit"
    elif role == "vp" and (record.high_value or record.escalated or record.status == "awaiting_vp"):
        back = "/approvals"
        nav = "approvals"
    else:
        back = "/exceptions"
        nav = "exceptions"
    return templates.TemplateResponse(
        request,
        "invoice_detail.html",
        _ctx(
            request,
            nav,
            record=record,
            events=events,
            stage_meta=_stage_meta(record),
            back_href=back,
        ),
    )


@app.post("/invoices/{record_id}/override")
async def override_invoice(
    request: Request,
    record_id: int,
    invoice_id: str = Form(...),
    vendor: str = Form(...),
    amount: str = Form(...),
    due_date: str = Form(""),
    items_text: str = Form(...),
    analyst_notes: str = Form(""),
) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    svc = _svc(request)
    try:
        svc.apply_overrides(
            record_id,
            invoice_id=invoice_id,
            vendor=vendor,
            amount=amount,
            due_date=due_date,
            items_text=items_text,
            analyst_notes=analyst_notes,
            actor_role=claims.actor,
        )
        return _redirect(
            f"/invoices/{record_id}",
            flash_kind="ok",
            flash_msg="Corrections saved and re-validated.",
        )
    except ValidationError as exc:
        return _redirect(f"/invoices/{record_id}", flash_kind="err", flash_msg=str(exc))


@app.post("/invoices/{record_id}/pay")
async def analyst_pay(request: Request, record_id: int) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "analyst":
        return _redirect(
            f"/invoices/{record_id}",
            flash_kind="err",
            flash_msg="Analyst pay is for AP Analysts. Switch role or use VP approve.",
        )
    svc = _svc(request)
    try:
        svc.analyst_submit_pay(record_id, actor=claims.actor)
        return _redirect("/audit", flash_kind="ok", flash_msg="Invoice paid.")
    except ValidationError as exc:
        return _redirect(f"/invoices/{record_id}", flash_kind="err", flash_msg=str(exc))


@app.post("/invoices/{record_id}/vp-pay")
async def vp_pay(request: Request, record_id: int) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "vp":
        return _redirect(
            f"/invoices/{record_id}",
            flash_kind="err",
            flash_msg="Only VP Approver can approve high-value payments.",
        )
    svc = _svc(request)
    try:
        svc.vp_approve_pay(
            record_id,
            note="VP approved from Control Centre",
            actor=claims.actor,
        )
        return _redirect("/audit", flash_kind="ok", flash_msg="VP approved and paid.")
    except ValidationError as exc:
        return _redirect(f"/invoices/{record_id}", flash_kind="err", flash_msg=str(exc))


@app.post("/invoices/{record_id}/escalate")
async def escalate(request: Request, record_id: int) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "analyst":
        return _redirect(
            f"/invoices/{record_id}",
            flash_kind="err",
            flash_msg="Only analysts escalate into the VP queue.",
        )
    svc = _svc(request)
    svc.escalate(record_id, actor_role=claims.actor, note="Escalated from Exceptions")
    return _redirect(
        "/exceptions",
        flash_kind="ok",
        flash_msg="Escalated to VP queue. Switch Working as → VP Approver to decide.",
    )


@app.post("/invoices/{record_id}/decline")
async def decline(request: Request, record_id: int) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    svc = _svc(request)
    try:
        svc.decline(
            record_id,
            actor_role=claims.actor,
            reason=f"Declined by {claims.actor}",
        )
        return _redirect("/audit", flash_kind="ok", flash_msg="Invoice declined.")
    except ValidationError as exc:
        return _redirect(f"/invoices/{record_id}", flash_kind="err", flash_msg=str(exc))


@app.post("/invoices/{record_id}/return")
async def return_to_analyst(request: Request, record_id: int) -> RedirectResponse:
    claims = _require_session(request)
    if isinstance(claims, RedirectResponse):
        return claims
    if claims.role != "vp":
        return _redirect(
            f"/invoices/{record_id}",
            flash_kind="err",
            flash_msg="Only VP Approver can return invoices to analysts.",
        )
    svc = _svc(request)
    svc.return_to_analyst(record_id, note="Returned from VP — please correct")
    return _redirect(
        "/exceptions", flash_kind="ok", flash_msg="Returned to Exceptions for analyst."
    )
