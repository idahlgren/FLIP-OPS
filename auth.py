"""
auth.py
=======

HTTP Basic Authentication for the Flask app.

Auth is enabled only when BOTH `APP_USER` and `APP_PASS` env vars are set.
If they aren't set, the app runs open (useful for local dev).

Wire it up with `before_request` in app.py:

    from auth import require_auth_globally
    app.before_request(require_auth_globally)
"""

from __future__ import annotations

import hmac
import os
from flask import request, Response


def _constant_time_equal(a: str, b: str) -> bool:
    """Compare strings without leaking timing information."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _check(username: str, password: str) -> bool:
    expected_user = os.environ.get("APP_USER", "")
    expected_pass = os.environ.get("APP_PASS", "")
    if not expected_user or not expected_pass:
        return False
    return (_constant_time_equal(username, expected_user)
            and _constant_time_equal(password, expected_pass))


def require_auth_globally():
    """
    Run before every request.  If APP_USER and APP_PASS are set, require
    matching Basic Auth headers.  Otherwise pass through (dev mode).

    Returns None to continue, or a Response to short-circuit.
    """
    if not (os.environ.get("APP_USER") and os.environ.get("APP_PASS")):
        return None  # auth disabled

    auth = request.authorization
    if auth and auth.username and auth.password:
        if _check(auth.username, auth.password):
            return None

    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="wholesale-tool"'},
    )
