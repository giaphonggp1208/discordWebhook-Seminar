from __future__ import annotations

import secrets
from hmac import compare_digest

from fastapi import HTTPException, Request, Response, status

CSRF_COOKIE = "leave_demo_csrf"
CSRF_HEADER = "X-CSRF-TOKEN"


def issue_csrf(response: Response) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="lax")
    return {"headerName": CSRF_HEADER, "token": token}


def require_csrf(request: Request) -> None:
    submitted, cookie = request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)
    if not submitted or not cookie or not compare_digest(submitted, cookie):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
