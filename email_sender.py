"""
email_sender.py
===============

Send outbound emails via Gmail SMTP using an app password.

Gmail app-password setup (one-time, from your friend's Gmail account):
  1. myaccount.google.com -> Security -> 2-Step Verification (enable if not)
  2. Search "App passwords" in Google Account settings
  3. Create a new one for "Mail" on "Other: wholesale-tool"
  4. Copy the 16-character password (spaces ignored)
  5. Set it as SMTP_PASS in Railway env vars

Env vars required for sending:
  SMTP_USER      full Gmail address
  SMTP_PASS      16-char app password (NOT the Gmail password)
  SMTP_FROM_NAME display name (e.g., "Alex Chen")

If any are missing, send_email() returns a warning instead of sending.
This lets the app run locally without Gmail credentials.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from dataclasses import dataclass
from typing import Optional


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


@dataclass
class SendResult:
    sent: bool
    error: Optional[str] = None
    from_address: Optional[str] = None


def _config() -> tuple[str, str, str]:
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    from_name = os.environ.get("SMTP_FROM_NAME", "").strip()
    return user, pw, from_name


def is_configured() -> bool:
    user, pw, _ = _config()
    return bool(user and pw)


def send_email(*, to: str, subject: str, body: str,
               reply_to: Optional[str] = None) -> SendResult:
    """
    Send a plain-text email.  Returns SendResult; never raises.

    Parameters
    ----------
    to         recipient email address
    subject    email subject
    body       plain-text body (the template output)
    reply_to   optional; defaults to SMTP_USER
    """
    user, pw, from_name = _config()
    if not (user and pw):
        return SendResult(
            sent=False,
            error="SMTP not configured (set SMTP_USER and SMTP_PASS)",
        )

    if not to or "@" not in to:
        return SendResult(sent=False, error=f"invalid recipient: {to!r}")

    msg = EmailMessage()
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = f"{from_name} <{user}>" if from_name else user
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
        return SendResult(sent=True, from_address=user)
    except smtplib.SMTPAuthenticationError as e:
        return SendResult(sent=False,
                          error=f"Gmail auth failed — check app password ({e.smtp_code})")
    except smtplib.SMTPException as e:
        return SendResult(sent=False, error=f"SMTP error: {e}")
    except (OSError, TimeoutError) as e:
        return SendResult(sent=False, error=f"network error: {e}")


if __name__ == "__main__":
    # Quick test — won't actually send unless env vars are set
    print(f"Configured: {is_configured()}")
    result = send_email(
        to="test@example.com",
        subject="Test from wholesale-tool",
        body="If you're reading this, SMTP works.",
    )
    print(f"Result: sent={result.sent}  error={result.error}")
