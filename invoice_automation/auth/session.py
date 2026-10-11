"""HMAC-signed workbench session cookies.

Notes
-----
Uses ``GALATIQ_SESSION_SECRET`` when set. Otherwise uses the PaymentPermit
secret from ``resolve_permit_secret``. This is local production-shaped auth,
not a live enterprise IdP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from invoice_automation.policy.engine import PolicyError, resolve_permit_secret

ALLOWED_ROLES = frozenset({"analyst", "vp"})
ALLOWED_LLMS = frozenset({"stub", "grok"})
DEFAULT_TTL_S = 12 * 60 * 60
COOKIE_NAME = "galatiq_session"


@dataclass(frozen=True)
class SessionClaims:
    """Verified workbench session claims.

    Parameters
    ----------
    role : str
        ``analyst`` or ``vp``.
    llm : str
        ``stub`` or ``grok``.
    sub : str
        Subject from mock OIDC (or role when missing).
    exp : int
        Unix expiry time.
    nonce : str
        Session nonce.
    """

    role: str
    llm: str
    sub: str
    exp: int
    nonce: str

    @property
    def actor(self) -> str:
        # Actor string for PaymentPermit issue paths.
        return self.sub if self.sub else self.role


def resolve_session_secret(secret: bytes | str | None = None) -> bytes:
    """Return HMAC bytes for session cookies.

    Parameters
    ----------
    secret : bytes or str or None
        Explicit secret. When None, prefer ``GALATIQ_SESSION_SECRET``,
        else fall back to the permit secret resolver.

    Returns
    -------
    bytes
        HMAC key material.

    Raises
    ------
    PolicyError
        When ``GALATIQ_SESSION_SECRET`` is set but shorter than 16 chars.
    """
    if secret is not None:
        if isinstance(secret, bytes):
            return secret
        return str(secret).encode("utf-8")
    raw = os.environ.get("GALATIQ_SESSION_SECRET", "").strip()
    if raw:
        if len(raw) < 16:
            raise PolicyError("GALATIQ_SESSION_SECRET is too short (<16)")
        return raw.encode("utf-8")
    return resolve_permit_secret()


def issue_session_cookie(
    *,
    role: str,
    llm: str = "stub",
    sub: str | None = None,
    ttl_s: int = DEFAULT_TTL_S,
    secret: bytes | str | None = None,
) -> str:
    """Build a signed session cookie value.

    Parameters
    ----------
    role : str
        ``analyst`` or ``vp``.
    llm : str
        ``stub`` or ``grok``.
    sub : str or None
        Subject from mock OIDC. Defaults to ``role``.
    ttl_s : int
        Lifetime in seconds.
    secret : bytes or str or None
        HMAC secret override.

    Returns
    -------
    str
        ``base64url(payload).hexmac`` cookie value.
    """
    role = role if role in ALLOWED_ROLES else "analyst"
    llm = llm if llm in ALLOWED_LLMS else "stub"
    payload = {
        "role": role,
        "llm": llm,
        "sub": (sub or role).strip() or role,
        "exp": int(time.time()) + int(ttl_s),
        "nonce": secrets.token_hex(8),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    mac = _mac(body, resolve_session_secret(secret))
    return f"{body}.{mac}"


def verify_session_cookie(
    value: str | None,
    *,
    secret: bytes | str | None = None,
    now: float | None = None,
) -> SessionClaims | None:
    """Verify a session cookie.

    Parameters
    ----------
    value : str or None
        Cookie value ``body.mac``.
    secret : bytes or str or None
        HMAC secret override.
    now : float or None
        Clock override for expiry checks.

    Returns
    -------
    SessionClaims or None
        Claims when valid. None when missing, bad MAC, or expired.
    """
    if not value or "." not in value:
        return None
    body, _, mac = value.partition(".")
    if not body or not mac:
        return None
    expected = _mac(body, resolve_session_secret(secret))
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        raw = _unb64(body)
        data: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    role = str(data.get("role", ""))
    llm = str(data.get("llm", "stub"))
    sub = str(data.get("sub", role) or role)
    exp = int(data.get("exp", 0))
    nonce = str(data.get("nonce", ""))
    ts = time.time() if now is None else now
    if role not in ALLOWED_ROLES or llm not in ALLOWED_LLMS:
        return None
    if exp < int(ts):
        return None
    return SessionClaims(role=role, llm=llm, sub=sub, exp=exp, nonce=nonce)


def _mac(body: str, secret: bytes) -> str:
    return hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()


def _b64(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    import base64

    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
