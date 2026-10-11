"""CLI entry point for the Galatiq invoice pipeline.

Notes
-----
The default engine is Grok. The default CLI output is a short JSON summary.
Use ``--llm=stub`` for offline runs. Use ``-v`` for the full audit.
The case CLI contract is::

    python main.py --invoice_path=data/invoices/invoice1.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key

from invoice_automation.adapters.llm_grok import GrokAuthError, GrokLLM
from invoice_automation.case_brief import is_live_xai_key
from invoice_automation.orchestration.pipeline import Pipeline, PipelineResult
from invoice_automation.policy.engine import PolicyError, resolve_permit_secret
from invoice_automation.sim.runner import run_case_simulation
from invoice_automation.telemetry.logging_setup import configure_logging

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _ensure_permit_secret() -> None:
    try:
        resolve_permit_secret()
    except PolicyError as exc:
        raise SystemExit(
            f"error: {exc}\n"
            "hint: python scripts/bootstrap_env.py   # creates .env + permit secret\n"
            "      then edit .env if needed"
        ) from exc


def _save_api_key(key: str) -> None:
    os.environ["XAI_API_KEY"] = key
    if not ENV_PATH.exists():
        ENV_PATH.write_text(
            f"XAI_API_KEY={key}\nXAI_MODEL=grok-3\nGALATIQ_PERMIT_SECRET=\n",
            encoding="utf-8",
        )
    else:
        set_key(str(ENV_PATH), "XAI_API_KEY", key)
    print(f"Saved XAI_API_KEY to {ENV_PATH}", file=sys.stderr)


def _prompt_enter_api_key() -> str | None:
    """Prompt for a key. Returns 'grok' if saved, None to redisplay menu."""
    key = getpass("XAI_API_KEY (input hidden): ").strip()
    if not is_live_xai_key(key):
        print(
            "That does not look like a live key (placeholder/empty). Try again.",
            file=sys.stderr,
        )
        return None
    _save_api_key(key)
    return "grok"


def _prompt_llm_choice(*, title: str, noninteractive_error: str) -> str:
    """Shared 1=key / 2=offline / q=quit prompt used for missing and bad keys."""
    if not sys.stdin.isatty():
        raise SystemExit(noninteractive_error)

    print(title, file=sys.stderr)
    while True:
        choice = input("Choose 1 / 2 / q: ").strip().lower()
        if choice in {"q", "quit"}:
            raise SystemExit("aborted")
        if choice in {"2", "stub", "offline", "o"}:
            print("Using offline stub.", file=sys.stderr)
            return "stub"
        if choice in {"1", "key", "k", "grok"}:
            result = _prompt_enter_api_key()
            if result is not None:
                return result
            continue
        print("Please enter 1, 2, or q.", file=sys.stderr)


def _prompt_llm_backend() -> str:
    """Ask for an API key or offline stub when Grok is selected but key is missing."""
    return _prompt_llm_choice(
        title=(
            "Grok is the default engine, but no live XAI_API_KEY was found.\n"
            "  [1] Enter an xAI API key now (saved to .env)\n"
            "  [2] Continue offline with the stub LLM\n"
            "  [q] Quit"
        ),
        noninteractive_error=(
            "error: default engine is Grok but XAI_API_KEY is missing/placeholder.\n"
            "hint: set XAI_API_KEY in .env, or pass --llm=stub for offline\n"
            "      (non-interactive shell — cannot prompt)"
        ),
    )


def _prompt_invalid_api_key() -> str:
    """Ask what to do when xAI rejects the configured key."""
    return _prompt_llm_choice(
        title=(
            "The XAI_API_KEY was rejected by xAI (incorrect or revoked).\n"
            "  [1] Enter a different xAI API key now (saved to .env)\n"
            "  [2] Continue offline with the stub LLM\n"
            "  [q] Quit"
        ),
        noninteractive_error=(
            "error: XAI_API_KEY was rejected by xAI (incorrect or revoked).\n"
            "hint: fix XAI_API_KEY in .env, or pass --llm=stub for offline\n"
            "      (non-interactive shell — cannot prompt)"
        ),
    )


def resolve_llm(requested: str) -> str:
    """Resolve the LLM backend name.

    Parameters
    ----------
    requested : str
        ``grok`` (default) or ``stub``.

    Returns
    -------
    str
        ``grok`` or ``stub``.

    Raises
    ------
    SystemExit
        If Grok is required, the key is missing, and the shell cannot prompt.
    """
    if requested == "stub":
        return "stub"
    if is_live_xai_key(os.getenv("XAI_API_KEY")):
        return "grok"
    return _prompt_llm_backend()


def ensure_llm_ready(llm: str) -> str:
    """Probe Grok credentials before invoice work.

    Parameters
    ----------
    llm : str
        Backend from :func:`resolve_llm`.

    Returns
    -------
    str
        ``grok`` when the key is accepted, else ``stub`` after operator choice.

    Raises
    ------
    SystemExit
        If xAI rejects the key and the shell cannot prompt.
    """
    if llm != "grok":
        return llm
    while True:
        try:
            # Fail fast on incorrect keys so extract never falls back silently.
            print("Checking XAI_API_KEY with xAI…", file=sys.stderr)
            GrokLLM().verify_credentials()
            return "grok"
        except GrokAuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            llm = _prompt_invalid_api_key()
            if llm == "stub":
                return "stub"


def summarize_result(result: PipelineResult) -> dict[str, Any]:
    """Build the compact CLI payload (default output).

    Parameters
    ----------
    result : PipelineResult
        Pipeline summary for one invoice.

    Returns
    -------
    dict
        Keys: invoice_id, status, vendor, amount, issues, approval_reason,
        llm_tokens_total.
    """
    vendor = ""
    amount = ""
    for event in result.events:
        if event.get("event_type") == "InvoiceExtracted":
            payload = event.get("payload") or {}
            vendor = str(payload.get("vendor") or "")
            amount = str(payload.get("amount") or "")
            break
    return {
        "invoice_id": result.invoice_id,
        "status": result.status,
        "vendor": vendor,
        "amount": amount,
        "issues": list(result.issues),
        "approval_reason": result.approval_reason,
        "llm_tokens_total": (result.metrics or {}).get("llm_tokens_total", 0),
    }


def full_result(result: PipelineResult) -> dict[str, Any]:
    """Build the verbose audit payload (``-v`` / ``--verbose``).

    Parameters
    ----------
    result : PipelineResult
        Pipeline summary for one invoice.

    Returns
    -------
    dict
        Includes events and metrics for audit review.
    """
    return {
        "invoice_id": result.invoice_id,
        "source_path": result.source_path,
        "status": result.status,
        "issues": list(result.issues),
        "approval_reason": result.approval_reason,
        "correlation_id": result.correlation_id,
        "events": result.events,
        "metrics": result.metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Galatiq Invoice Pipeline")
    parser.add_argument("--invoice_path", type=str, help="Path to a single invoice file")
    parser.add_argument("--all", action="store_true", help="Process data/invoices/")
    parser.add_argument(
        "--sim",
        choices=["case"],
        default=None,
        help="Run Case Simulation Contract (W1–W10 harness)",
    )
    parser.add_argument(
        "--llm",
        choices=["stub", "grok"],
        default="grok",
        help="LLM backend (default: grok; prompts for key or offline if missing/invalid)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print full events + metrics JSON (default is a short summary)",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=str(ROOT / "data" / "invoices"),
        help="Invoice directory for --all / --sim",
    )
    parser.add_argument(
        "--work_dir",
        type=str,
        default=".galatiq_runtime",
        help="Runtime DB / event log directory",
    )
    parser.add_argument(
        "--max_steps",
        type=int,
        default=200,
        help="Drain iteration budget (default 200)",
    )
    return parser


def _system_exit_code(exc: SystemExit) -> int:
    code = exc.code
    if code in (None, 0):
        return 0
    if code == "aborted":
        return 1
    if isinstance(code, str):
        print(code, file=sys.stderr)
        return 2
    return int(code) if isinstance(code, int) else 2


def main(argv: list[str] | None = None) -> int:
    """Run the invoice pipeline from the command line.

    Parameters
    ----------
    argv : list of str or None
        Argument list. ``None`` uses ``sys.argv``.

    Returns
    -------
    int
        Process exit code (0 success, 1 aborted/failed sim, 2 config/runtime error).
    """
    load_dotenv(ENV_PATH)
    load_dotenv()
    configure_logging()

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        _ensure_permit_secret()
        llm = ensure_llm_ready(resolve_llm(args.llm))
    except SystemExit as exc:
        return _system_exit_code(exc)

    use_grok = llm == "grok"

    if args.sim == "case":
        sim_dir = Path(args.work_dir) / "case_sim"
        try:
            report = run_case_simulation(
                sim_dir,
                data_dir=args.data_dir,
                use_grok=use_grok,
            )
        except GrokAuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report.to_dict(), indent=2))
        report.save(sim_dir / "last_report.json")
        return 0 if report.ok else 1

    try:
        pipe = Pipeline(
            work_dir=args.work_dir,
            use_grok=use_grok,
            max_steps=args.max_steps,
        )
    except (RuntimeError, Exception) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.all:
        try:
            results = pipe.process_directory(args.data_dir)
        except GrokAuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        for r in results:
            payload = full_result(r) if args.verbose else summarize_result(r)
            print(json.dumps(payload, indent=2, default=str))
        print(
            json.dumps(
                {"count": len(results), "metrics": pipe.metrics.snapshot()},
                indent=2,
            )
        )
        return 0

    if args.invoice_path:
        try:
            result = pipe.process_file(args.invoice_path)
        except GrokAuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        payload = full_result(result) if args.verbose else summarize_result(result)
        print(json.dumps(payload, indent=2, default=str))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
