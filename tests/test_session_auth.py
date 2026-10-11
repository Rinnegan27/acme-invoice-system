"""Signed session + mock IdP + forged cookie rejection."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_automation.auth import MockOidcIdp, issue_session_cookie, verify_session_cookie
from invoice_automation.auth.session import COOKIE_NAME

pytestmark = pytest.mark.white_box

SECRET = b"test-session-secret-16b"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_PERMIT_SECRET", "ci-test-secret-do-not-use-in-prod")
    monkeypatch.setenv("GALATIQ_SESSION_SECRET", SECRET.decode("utf-8"))


def test_issue_and_verify_session_roundtrip() -> None:
    cookie = issue_session_cookie(role="vp", llm="stub", sub="vp@acme.local", secret=SECRET)
    claims = verify_session_cookie(cookie, secret=SECRET)
    assert claims is not None
    assert claims.role == "vp"
    assert claims.actor == "vp@acme.local"


def test_forged_unsigned_role_cookie_ignored() -> None:
    assert verify_session_cookie("vp.forged", secret=SECRET) is None
    assert verify_session_cookie(None, secret=SECRET) is None


def test_mock_oidc_issues_token() -> None:
    idp = MockOidcIdp(secret=SECRET)
    token = idp.authenticate("vp@acme.local")
    assert token is not None
    assert token.role == "vp"
    again = idp.introspect(token.access_token)
    assert again is not None
    assert again.sub == "vp@acme.local"


def test_pay_requires_signed_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_WORK_DIR", str(tmp_path / "wb"))
    # Import app after env so deps pick up temp paths if used.
    from web.deps import get_service

    get_service.cache_clear()
    from web.app import app

    client = TestClient(app)
    # Forge legacy unsigned VP cookie — must not authorize pay.
    r = client.post(
        "/invoices/1/vp-pay",
        cookies={"galatiq_role": "vp", "galatiq_llm": "stub"},
        follow_redirects=False,
    )
    assert r.status_code in {303, 307}
    assert "/login" in r.headers.get("location", "")


def test_signed_session_reaches_vp_desk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALATIQ_WORK_DIR", str(tmp_path / "wb2"))
    from web.deps import get_service

    get_service.cache_clear()
    from web.app import app

    client = TestClient(app)
    cookie = issue_session_cookie(role="vp", llm="stub", sub="vp@acme.local", secret=SECRET)
    r = client.get("/approvals", cookies={COOKIE_NAME: cookie})
    assert r.status_code == 200
    assert "Approvals" in r.text
