"""CLI human-in-the-loop gate for VP-required invoices.

Notes
-----
Case brief: operators historically obtained VP approval (email chains). The
Control Centre covers desk workflows; the CLI must also allow a human to
approve, reject, or escalate to the automated VP agent when scrutiny applies.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Literal

from invoice_automation.domain.models import Invoice
from invoice_automation.policy.invariants import partition_soft_escalation_issues

HumanAction = Literal["approve", "reject", "escalate"]


def needs_human_or_vp_gate(invoice: Invoice) -> bool:
    """Return True when high-value or soft escalations require scrutiny.

    Parameters
    ----------
    invoice : Invoice
        Validated invoice (may carry soft issues).

    Returns
    -------
    bool
        True when amount ≥ $10k or soft escalations are present.
    """
    _hard, soft = partition_soft_escalation_issues(invoice.issues)
    return bool(invoice.is_high_value or soft)


def cli_human_gate_enabled(*, force: bool | None = None) -> bool:
    """Whether the CLI should prompt for human approve/reject/escalate.

    Parameters
    ----------
    force : bool or None
        Explicit CLI flag. ``True`` forces on, ``False`` forces auto-VP,
        ``None`` uses TTY + env defaults.

    Notes
    -----
    Non-interactive shells and ``GALATIQ_CLI_AUTO_VP=1`` keep the automated
    VP agent (CI / ``--sim`` / pipes).
    """
    if force is False:  # --auto-vp
        return False
    if force is True:  # --human-approval
        return True
    if os.environ.get("GALATIQ_CLI_AUTO_VP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    return bool(sys.stdin.isatty())


def prompt_human_approval(invoice: Invoice) -> HumanAction:
    """Prompt on stderr/stdin for approve, reject, or escalate-to-VP-agent.

    Parameters
    ----------
    invoice : Invoice
        Validated invoice awaiting scrutiny.

    Returns
    -------
    HumanAction
        ``approve``, ``reject``, or ``escalate`` (automated VP agent).

    Raises
    ------
    SystemExit
        When the operator quits or stdin is not interactive.
    """
    if not sys.stdin.isatty():
        raise SystemExit(
            "error: VP scrutiny required but shell is non-interactive.\n"
            "hint: run in a TTY for human approve/reject/escalate, or set "
            "GALATIQ_CLI_AUTO_VP=1 / pass --auto-vp for the automated VP agent"
        )

    _hard, soft = partition_soft_escalation_issues(invoice.issues)
    print("", file=sys.stderr)
    print("── Human / VP scrutiny required ──", file=sys.stderr)
    print(f"  invoice_id : {invoice.invoice_id}", file=sys.stderr)
    print(f"  vendor     : {invoice.vendor}", file=sys.stderr)
    print(f"  amount     : {invoice.amount}", file=sys.stderr)
    print(f"  high_value : {invoice.is_high_value}", file=sys.stderr)
    if soft:
        print(f"  soft       : {', '.join(soft)}", file=sys.stderr)
    items = ", ".join(f"{i.sku}×{i.quantity}" for i in invoice.items[:8])
    if items:
        print(f"  items      : {items}", file=sys.stderr)
    print(
        "  [a] Approve and pay (human)\n"
        "  [r] Reject (human)\n"
        "  [e] Escalate to automated VP agent (Grok/stub reflection)\n"
        "  [q] Quit",
        file=sys.stderr,
    )
    while True:
        choice = input("Choose a / r / e / q: ").strip().lower()
        if choice in {"q", "quit"}:
            raise SystemExit("aborted")
        if choice in {"a", "approve", "y", "yes"}:
            return "approve"
        if choice in {"r", "reject", "n", "no"}:
            return "reject"
        if choice in {"e", "escalate", "vp"}:
            return "escalate"
        print("Please enter a, r, e, or q.", file=sys.stderr)


def make_cli_human_gate() -> Callable[[Invoice], HumanAction]:
    """Build a Pipeline ``human_gate`` that prompts on the CLI.

    Returns
    -------
    callable
        ``(invoice) -> HumanAction`` bound to :func:`prompt_human_approval`.
    """

    def _gate(invoice: Invoice) -> HumanAction:
        return prompt_human_approval(invoice)

    return _gate
