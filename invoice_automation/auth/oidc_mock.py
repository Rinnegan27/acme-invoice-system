"""Local mock OIDC IdP for enterprise-shaped login without a live tenant.

Notes
-----
Exchanges a demo username for a mock access token and workbench role.
Replace this module with a real OIDC client when wiring Okta/Auth0.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from invoice_automation.auth.session import resolve_session_secret

# Demo users only — not production identities.
_DEMO_USERS: dict[str, dict[str, str]] = {
    "analyst@acme.local": {"role": "analyst", "sub": "analyst@acme.local", "name": "AP Analyst"},
    "vp@acme.local": {"role": "vp", "sub": "vp@acme.local", "name": "VP Approver"},
    "analyst": {"role": "analyst", "sub": "analyst@acme.local", "name": "AP Analyst"},
    "vp": {"role": "vp", "sub": "vp@acme.local", "name": "VP Approver"},
}


@dataclass(frozen=True)
class MockToken:
    """Opaque mock access token claims.

    Parameters
    ----------
    access_token : str
        Signed mock token string.
    role : str
        Workbench role (``analyst`` or ``vp``).
    sub : str
        Subject bound into the session cookie.
    name : str
        Display name for the login UI.
    exp : int
        Unix expiry time.
    """

    access_token: str
    role: str
    sub: str
    name: str
    exp: int


class MockOidcIdp:
    """Passwordless mock IdP for local demos.

    Parameters
    ----------
    secret : bytes or str or None
        HMAC secret for mock tokens. Defaults to the session secret.
    ttl_s : int
        Token lifetime in seconds.

    Notes
    -----
    Demo users only. Replace this class with a real OIDC client for a live
    Okta or Auth0 tenant.
    """

    issuer = "https://mock-idp.galatiq.local"

    def __init__(self, *, secret: bytes | str | None = None, ttl_s: int = 3600) -> None:
        self._secret = resolve_session_secret(secret)
        self._ttl_s = ttl_s

    def list_users(self) -> list[dict[str, str]]:
        # Demo usernames for the login form.
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for key, meta in _DEMO_USERS.items():
            if "@" not in key:
                continue
            if meta["sub"] in seen:
                continue
            seen.add(meta["sub"])
            out.append({"username": key, "role": meta["role"], "name": meta["name"]})
        return out

    def authenticate(self, username: str) -> MockToken | None:
        """Issue a mock access token for a known demo user.

        Parameters
        ----------
        username : str
            Demo username or email.

        Returns
        -------
        MockToken or None
            Token when the user is known. None otherwise.
        """
        meta = _DEMO_USERS.get((username or "").strip().lower()) or _DEMO_USERS.get(
            (username or "").strip()
        )
        if meta is None:
            # Case-insensitive email lookup.
            for key, value in _DEMO_USERS.items():
                if key.lower() == (username or "").strip().lower():
                    meta = value
                    break
        if meta is None:
            return None
        exp = int(time.time()) + self._ttl_s
        payload = {
            "iss": self.issuer,
            "sub": meta["sub"],
            "role": meta["role"],
            "name": meta["name"],
            "exp": exp,
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        mac = hmac.new(self._secret, body.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"mock.{_b64(body.encode('utf-8'))}.{mac}"
        return MockToken(
            access_token=token,
            role=meta["role"],
            sub=meta["sub"],
            name=meta["name"],
            exp=exp,
        )

    def introspect(self, access_token: str) -> MockToken | None:
        """Validate a mock access token.

        Parameters
        ----------
        access_token : str
            Token from :meth:`authenticate`.

        Returns
        -------
        MockToken or None
            Claims when the MAC and expiry are valid. None otherwise.
        """
        if not access_token.startswith("mock."):
            return None
        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        _, body_b64, mac = parts
        try:
            body = _unb64(body_b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        expected = hmac.new(self._secret, body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return None
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return MockToken(
            access_token=access_token,
            role=str(data.get("role", "analyst")),
            sub=str(data.get("sub", "analyst")),
            name=str(data.get("name", "")),
            exp=int(data.get("exp", 0)),
        )


def _b64(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    import base64

    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
