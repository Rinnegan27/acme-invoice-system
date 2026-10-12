"""HMAC PaymentPermit fence.

Notes
-----
LLM text cannot authorize payment. Permits are single-use.
Consumed nonces persist in SQLite ``consumed_permits``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from invoice_automation.adapters.sqlite_db import connect
from invoice_automation.domain.exceptions import ValidationError
from invoice_automation.domain.models import Invoice
from invoice_automation.policy.invariants import collect_invariant_issues

# Hard stops — never payable, even with override.
HARD_BLOCK_PREFIXES: tuple[str, ...] = (
    "unknown_item",
    "invalid_quantity",
    "negative_amount",
    "zero_stock",
    "invalid_sku_charset",
    "negative_unit_price",
    "suspicious_vendor_text",
)

# Soft findings need an explicit override permit.
SOFT_PREFIXES: tuple[str, ...] = (
    "insufficient_stock",
    "missing_vendor",
    "amount_line_mismatch",
    "price_mismatch",
    "no_po_match",
    "po_qty_exceeded",
    "sku_typo_review",
    "vendor_split_risk",
    "vendor_injection_review",
    "sku_variant_review",
)

_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "galatiq-dev-permit-key",
        "change-me-in-production",
        "changeme",
        "replace-me",
        "local-dev-secret-replace-before-share",
    }
)
_MIN_SECRET_LEN = 16


class PolicyError(ValidationError):
    """Raised when a payment permit cannot be issued or verified."""


@dataclass(frozen=True)
class PaymentPermit:
    """Single-use authorization for the payment node.

    Parameters
    ----------
    correlation_id : str
        Run correlation id.
    invoice_id : str
        Business invoice id.
    invoice_hash : str
        Hash of pay-critical invoice fields.
    actor : str
        Actor that issued the permit.
    allow_soft_override : bool
        When True, soft findings may pass with this permit.
    exp : float
        Unix expiry time.
    nonce : str
        Single-use nonce stored after consume.
    mac : str
        HMAC authenticity tag.
    """

    correlation_id: str
    invoice_id: str
    invoice_hash: str
    actor: str
    allow_soft_override: bool
    exp: float
    nonce: str
    mac: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentPermit:
        return cls(
            correlation_id=str(data["correlation_id"]),
            invoice_id=str(data["invoice_id"]),
            invoice_hash=str(data["invoice_hash"]),
            actor=str(data["actor"]),
            allow_soft_override=bool(data.get("allow_soft_override", False)),
            exp=float(data["exp"]),
            nonce=str(data["nonce"]),
            mac=str(data["mac"]),
        )


def _persist_permit_secret(secret: str) -> None:
    """Write GALATIQ_PERMIT_SECRET into the local .env (gitignored)."""
    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    line = f"GALATIQ_PERMIT_SECRET={secret}"
    if not env_path.exists():
        env_path.write_text(
            f"XAI_API_KEY=\nXAI_MODEL=grok-3\n{line}\n",
            encoding="utf-8",
        )
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    found = False
    for row in lines:
        if row.startswith("GALATIQ_PERMIT_SECRET="):
            out.append(line)
            found = True
        else:
            out.append(row)
    if not found:
        out.append(line)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _auto_create_permit_secret() -> bytes:
    """Create a strong secret when the env value is blank (local/dev convenience)."""
    import secrets
    import sys

    generated = secrets.token_hex(32)
    os.environ["GALATIQ_PERMIT_SECRET"] = generated
    try:
        _persist_permit_secret(generated)
        print(
            "GALATIQ_PERMIT_SECRET was empty — created a local secret and saved it to .env.",
            file=sys.stderr,
        )
    except OSError:
        print(
            "GALATIQ_PERMIT_SECRET was empty — using a session-only secret (could not write .env).",
            file=sys.stderr,
        )
    return generated.encode("utf-8")


def resolve_permit_secret(secret: bytes | str | None = None) -> bytes:
    """Return a non-placeholder HMAC secret.

    Parameters
    ----------
    secret : bytes or str or None
        Explicit secret. When None, read ``GALATIQ_PERMIT_SECRET``.
        When the env value is blank, a strong secret is created and saved to
        ``.env`` so the key can be omitted from source control.

    Returns
    -------
    bytes
        Secret bytes for HMAC.

    Raises
    ------
    PolicyError
        If an explicit secret is too short or a known placeholder.
    """
    if secret is None:
        raw = os.environ.get("GALATIQ_PERMIT_SECRET", "")
        if not raw.strip():
            # Blank env is allowed: auto-create so operators can remove the line.
            return _auto_create_permit_secret()
    elif isinstance(secret, bytes):
        raw = secret.decode("utf-8")
    else:
        raw = str(secret)
    raw = raw.strip()
    lowered = raw.lower()
    if (
        not raw
        or lowered in {s.lower() for s in _PLACEHOLDER_SECRETS}
        or "replace-before" in lowered
        or "change-me" in lowered
        or len(raw) < _MIN_SECRET_LEN
    ):
        raise PolicyError(
            "GALATIQ_PERMIT_SECRET is missing, too short (<16), or a placeholder — "
            "leave it blank to auto-create, or set a real secret in .env"
        )
    return raw.encode("utf-8")


def invoice_payload_hash(
    *,
    invoice_id: str,
    vendor: str,
    amount: Decimal | str,
    items: list[dict[str, Any]] | tuple[Any, ...],
    due_date: str | None = None,
) -> str:
    """Hash business payload only (no source_path / correlation_id).

    Notes
    -----
    Used for payment dedupe across file formats and for revision detection
    when the same ``invoice_id`` returns with updated lines or totals.
    """
    norm_items: list[dict[str, Any]] = []
    for raw in items:
        if hasattr(raw, "sku"):
            sku = str(raw.sku)
            qty = int(raw.quantity)
            price = raw.unit_price
        else:
            sku = str(raw.get("sku"))
            qty = int(raw.get("quantity") or 0)
            price = raw.get("unit_price")
        norm_items.append(
            {
                "sku": sku,
                "quantity": qty,
                "unit_price": None if price in (None, "") else str(Decimal(str(price))),
            }
        )
    norm_items.sort(key=lambda row: (row["sku"], row["quantity"], row["unit_price"] or ""))
    amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    for row in norm_items:
        if row["unit_price"] is not None:
            row["unit_price"] = format(Decimal(row["unit_price"]).quantize(Decimal("0.01")), "f")
    payload = {
        "invoice_id": str(invoice_id),
        "vendor": str(vendor or "").strip(),
        "amount": format(amt, "f"),
        "due_date": due_date,
        "items": norm_items,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def invoice_content_hash(invoice: Invoice) -> str:
    """Stable hash of pay-critical invoice fields (includes run binding)."""
    payload = {
        "invoice_id": invoice.invoice_id,
        "vendor": invoice.vendor,
        "amount": str(invoice.amount),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "items": [
            {
                "sku": i.sku,
                "quantity": i.quantity,
                "unit_price": str(i.unit_price) if i.unit_price is not None else None,
            }
            for i in invoice.items
        ],
        "source_path": invoice.source_path,
        "correlation_id": invoice.correlation_id,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _is_hard(issue: str) -> bool:
    return any(issue.startswith(p) for p in HARD_BLOCK_PREFIXES) or issue.startswith(
        ("invalid_sku_charset", "negative_unit_price", "suspicious_vendor_text")
    )


def _is_soft(issue: str) -> bool:
    return any(issue.startswith(p) for p in SOFT_PREFIXES)


class PolicyEngine:
    """Issue and verify payment permits.

    Notes
    -----
    Do not call from LLM tool handlers. LLM text must not authorize pay.
    """

    def __init__(
        self,
        secret: bytes | str | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        self._secret = resolve_permit_secret(secret)
        self._db_path = Path(db_path) if db_path is not None else None
        self._lock = Lock()
        if self._db_path is not None:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        assert self._db_path is not None
        with connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_permits (
                    nonce           TEXT    PRIMARY KEY,
                    invoice_id      TEXT    NOT NULL,
                    correlation_id  TEXT    NOT NULL,
                    consumed_at     REAL    NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.commit()

    def _sign(self, parts: dict[str, Any]) -> str:
        body = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def issue_permit(
        self,
        invoice: Invoice,
        *,
        actor: str,
        open_issues: Iterable[str] = (),
        allow_soft_override: bool = False,
        ttl_s: float = 600.0,
    ) -> PaymentPermit:
        """Create a permit or raise PolicyError."""
        issues = list(open_issues) + collect_invariant_issues(invoice)
        seen: set[str] = set()
        uniq: list[str] = []
        for i in issues:
            if i not in seen:
                seen.add(i)
                uniq.append(i)

        hard = [i for i in uniq if _is_hard(i)]
        if hard:
            raise PolicyError(f"Hard policy block — no permit: {', '.join(hard)}")

        soft = [i for i in uniq if not _is_hard(i)]
        if soft and not allow_soft_override:
            raise PolicyError(f"Open findings block permit (override required): {', '.join(soft)}")

        if invoice.amount <= 0:
            raise PolicyError("Non-positive amount — no permit")

        nonce = uuid4().hex
        exp = time.time() + ttl_s
        invoice_hash = invoice_content_hash(invoice)
        unsigned = {
            "correlation_id": invoice.correlation_id,
            "invoice_id": invoice.invoice_id,
            "invoice_hash": invoice_hash,
            "actor": actor,
            "allow_soft_override": allow_soft_override,
            "exp": exp,
            "nonce": nonce,
        }
        mac = self._sign(unsigned)
        return PaymentPermit(mac=mac, **unsigned)  # type: ignore[arg-type]

    def verify_permit(
        self,
        permit: PaymentPermit | dict[str, Any],
        invoice: Invoice,
        *,
        open_issues: Iterable[str] | None = None,
        consume: bool = True,
    ) -> PaymentPermit:
        """Verify MAC, expiry, hash, and durable single-use nonce."""
        if isinstance(permit, dict):
            permit = PaymentPermit.from_dict(permit)

        unsigned = {
            "correlation_id": permit.correlation_id,
            "invoice_id": permit.invoice_id,
            "invoice_hash": permit.invoice_hash,
            "actor": permit.actor,
            "allow_soft_override": permit.allow_soft_override,
            "exp": permit.exp,
            "nonce": permit.nonce,
        }
        expected = self._sign(unsigned)
        if not hmac.compare_digest(expected, permit.mac):
            raise PolicyError("PaymentPermit MAC invalid")
        if time.time() > permit.exp:
            raise PolicyError("PaymentPermit expired")
        if permit.correlation_id != invoice.correlation_id:
            raise PolicyError("PaymentPermit correlation mismatch")
        if permit.invoice_id != invoice.invoice_id:
            raise PolicyError("PaymentPermit invoice_id mismatch")
        current_hash = invoice_content_hash(invoice)
        if permit.invoice_hash != current_hash:
            raise PolicyError("PaymentPermit invoice hash mismatch — state drifted")

        issues = list(open_issues) if open_issues is not None else list(invoice.issues)
        issues = issues + collect_invariant_issues(invoice)
        hard = [i for i in issues if _is_hard(i)]
        if hard:
            raise PolicyError(f"Hard block at verify: {', '.join(hard)}")
        soft = [i for i in issues if not _is_hard(i)]
        if soft and not permit.allow_soft_override:
            raise PolicyError(f"Soft findings without override permit: {', '.join(soft)}")

        if consume:
            self._consume_nonce(permit)
        return permit

    def _consume_nonce(self, permit: PaymentPermit) -> None:
        if self._db_path is None:
            raise PolicyError(
                "PolicyEngine has no db_path — cannot durably consume PaymentPermit nonce"
            )
        with self._lock:
            with connect(self._db_path) as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO consumed_permits (nonce, invoice_id, correlation_id, consumed_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            permit.nonce,
                            permit.invoice_id,
                            permit.correlation_id,
                            time.time(),
                        ),
                    )
                    conn.commit()
                except sqlite3.IntegrityError as exc:
                    raise PolicyError("PaymentPermit nonce already consumed") from exc


# Process-wide engine configured by Pipeline (db-backed).
_default_engine: PolicyEngine | None = None
_engine_lock = Lock()


def configure_policy_engine(
    *,
    db_path: str | Path,
    secret: bytes | str | None = None,
) -> PolicyEngine:
    """Install the process PolicyEngine used by workers."""
    global _default_engine
    engine = PolicyEngine(secret=secret, db_path=db_path)
    with _engine_lock:
        _default_engine = engine
    return engine


def get_policy_engine() -> PolicyEngine:
    global _default_engine
    with _engine_lock:
        if _default_engine is None:
            raise PolicyError(
                "PolicyEngine not configured — Pipeline must call configure_policy_engine "
                "with a system.db path and GALATIQ_PERMIT_SECRET"
            )
        return _default_engine


def reset_policy_engine_for_tests() -> None:
    """Clear the process engine (tests only)."""
    global _default_engine
    with _engine_lock:
        _default_engine = None
