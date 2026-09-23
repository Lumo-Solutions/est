from __future__ import annotations

from fastapi import Response

from app.core.config import Settings

SESSION_COOKIE = "__Host-ins_sid"
CSRF_COOKIE = "__Host-ins_csrf"


def set_session_cookies(response: Response, settings: Settings, session_id: str, csrf_token: str) -> None:
    # __Host- prefix requires: Secure, Path=/, no Domain attribute -- browsers
    # enforce this, which is why COOKIE_DOMAIN is not used here even though
    # it's configurable for non-__Host- deployments.
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=settings.session_ttl_s,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.session_ttl_s,
        secure=settings.cookie_secure,
        httponly=False,  # readable by JS: sent back as the X-CSRF-Token header (double-submit)
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
