"""
templates.py
============

Outreach template library.  Nine templates total: three archetypes
(probate, pre_foreclosure, general) × three channels (email, mail, call).

No LLM personalization in v1 — if the operator wants to tweak a draft,
they edit it directly in the compose screen.  Manual send, always.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional


TEMPLATES = {
    ("probate", "email"): {
        "id": "probate_email_v1",
        "subject": "Re: the house on {street_name}",
        "body": (
            "Hi {owner_first_name},\n\n"
            "I saw the property at {property_address} has been in the family "
            "for a while, and it looks like it's now on your plate to figure out. "
            "Managing an inherited place from a distance is rarely simple.\n\n"
            "I'm a local buyer in Memphis and I buy houses like this as-is — "
            "no repairs, no showings, no agent fees. If you're open to it, I'd "
            "love to put together a fair cash number this week.\n\n"
            "Would you be open to a short call Thursday or Friday?\n\n"
            "— {sender_name}\n{business_name} · Memphis, TN"
        ),
    },
    ("probate", "mail"): {
        "id": "probate_mail_v1",
        "subject": None,
        "body": (
            "Dear {owner_first_name},\n\n"
            "I know inheriting a property comes with a lot — paperwork, distance, "
            "sometimes memories you're not ready to sort through. I live and buy "
            "houses here in Memphis, and I work with families in your situation.\n\n"
            "If selling {property_address} quietly would be a weight off, I'd like "
            "to be the one to help. Cash, as-is, on your timeline.\n\n"
            "You can reach me at {sender_phone} any time. No pressure, no obligation.\n\n"
            "Warmly,\n{sender_name}\n{business_name}"
        ),
    },
    ("probate", "call"): {
        "id": "probate_call_v1",
        "subject": None,
        "body": (
            "OPENER:\nHi, is this {owner_first_name}? This is {sender_name} "
            "calling from Memphis. I'm a local buyer and I'm calling about "
            "the property on {street_name}. Got a minute?\n\n"
            "IF YES:\nI understand the place came to you through family. "
            "I buy houses like this as-is, for cash, without repairs or showings.\n\n"
            "QUESTIONS (in order):\n"
            "  1. How are you thinking about it — keep, rent, or sell?\n"
            "  2. When was the last time anyone was out there?\n"
            "  3. Any tenants or family using it?\n"
            "  4. What kind of shape do you think it's in?\n"
            "  5. Any back taxes or liens?\n"
            "  6. If you sold, what number makes it worth your time?\n\n"
            "DO NOT:\n"
            "  · Throw out a number first. Let them anchor.\n"
            "  · Say 'wholesaler' or 'assignment'.\n"
            "  · Promise a number before seeing comps and condition.\n\n"
            "CLOSE:\nI'll pull comps, get back to you {tomorrow_day} with a range."
        ),
    },
    ("pre_foreclosure", "email"): {
        "id": "pre_foreclosure_email_v1",
        "subject": "About {property_address}",
        "body": (
            "Hi {owner_first_name},\n\n"
            "I understand the situation at {property_address} may be coming "
            "to a head. I'm not a bank or a lender — I'm a local Memphis buyer, "
            "and I've helped families in your position get out ahead of "
            "foreclosure with cash in hand.\n\n"
            "Reply or call me at {sender_phone}. Even if we don't do business, "
            "I can point you to people who help for free.\n\n"
            "— {sender_name}\n{business_name}"
        ),
    },
    ("pre_foreclosure", "mail"): {
        "id": "pre_foreclosure_mail_v1",
        "subject": None,
        "body": (
            "Dear {owner_first_name},\n\n"
            "I understand the situation at {property_address} may be heading "
            "somewhere no one wants it to go. I'm a local Memphis buyer, and "
            "I work with homeowners who need to move fast.\n\n"
            "Cash, as-is, close in 10 days. You walk away with money in pocket, "
            "not a foreclosure on your record.\n\n"
            "Call me at {sender_phone} — no pressure.\n\n"
            "— {sender_name}\n{business_name}"
        ),
    },
    ("pre_foreclosure", "call"): {
        "id": "pre_foreclosure_call_v1",
        "subject": None,
        "body": (
            "OPENER:\nHi, is this {owner_first_name}? {sender_name} here, "
            "local buyer in Memphis. Calling about {street_name}.\n\n"
            "IF THEY'RE OPEN:\nI buy houses for cash before foreclosure. "
            "Closed deals in 10 days when people needed it. No fees, no repairs.\n\n"
            "QUESTIONS:\n"
            "  1. How far behind are you?\n"
            "  2. Has the bank given you a date?\n"
            "  3. What would walking away with cash look like for you?\n"
            "  4. Still living there?\n"
            "  5. Any other liens or taxes?\n\n"
            "TONE: calm, not urgent. They have enough urgency already.\n"
            "DO NOT promise anything before you've seen the house and comps."
        ),
    },
    ("general", "email"): {
        "id": "general_email_v1",
        "subject": "About {property_address}",
        "body": (
            "Hi {owner_first_name},\n\n"
            "I'm {sender_name}, a local Memphis buyer. I'm interested in "
            "{property_address} and wanted to see if selling might make sense.\n\n"
            "Cash, as-is, no repairs or fees. Reply or call {sender_phone}.\n\n"
            "— {sender_name}\n{business_name}"
        ),
    },
    ("general", "mail"): {
        "id": "general_mail_v1",
        "subject": None,
        "body": (
            "Dear {owner_first_name},\n\n"
            "I'm {sender_name}, a local buyer in Memphis. I'm interested in "
            "{property_address} and wanted to see if selling would be of "
            "interest to you.\n\n"
            "Cash, as-is, your timeline. Call me at {sender_phone}.\n\n"
            "— {sender_name}\n{business_name}"
        ),
    },
    ("general", "call"): {
        "id": "general_call_v1",
        "subject": None,
        "body": (
            "OPENER:\nHi, is this {owner_first_name}? {sender_name}, local "
            "buyer in Memphis. Calling about {street_name} — got a minute?\n\n"
            "QUESTIONS:\n"
            "  1. How long have you owned it?\n"
            "  2. Anyone living there now?\n"
            "  3. What kind of condition is it in?\n"
            "  4. Ever thought about selling?\n"
            "  5. If so, what price would make it worth your time?\n\n"
            "DO NOT push. Not interested today = mark dead, move on."
        ),
    },
}


# ---------------------------------------------------------------------------
# Compliance footers
# ---------------------------------------------------------------------------

def _email_footer(business_name: str, business_address: str) -> str:
    return (f"\n\n—\n{business_name}\n{business_address}\n"
            f"To stop receiving emails from us, reply UNSUBSCRIBE.")


def _mail_footer(business_name: str, business_address: str) -> str:
    return (f"\n\n{business_name}\n{business_address}\n"
            f"This is a solicitation for business. To opt out of future "
            f"mailings, return this letter with OPT OUT on the front.")


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

def compose(lead: dict, *, archetype: str, channel: str,
            sender_name: str, sender_phone: str,
            business_name: str, business_address: str) -> dict:
    """
    Render a template for a given lead + archetype + channel.
    Falls back to "general" if archetype not found.
    Returns {template_id, subject, body, warnings}.
    """
    assert channel in ("email", "mail", "call")

    tpl = TEMPLATES.get((archetype, channel)) or TEMPLATES[("general", channel)]

    vars_ = _build_vars(lead, sender_name=sender_name,
                        sender_phone=sender_phone,
                        business_name=business_name)

    body, missing_body = _render(tpl["body"], vars_)
    subject, missing_subj = (_render(tpl["subject"], vars_)
                             if tpl["subject"] else (None, []))

    if channel == "email":
        body += _email_footer(business_name, business_address)
    elif channel == "mail":
        body += _mail_footer(business_name, business_address)

    missing = sorted(set(missing_body + missing_subj))
    warnings = []
    if missing:
        warnings.append(f"unfilled placeholders: {', '.join(missing)}")
    if channel == "email" and not subject:
        warnings.append("no subject line")

    return {
        "template_id": tpl["id"],
        "subject": subject,
        "body": body,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _build_vars(lead: dict, *, sender_name: str, sender_phone: str,
                business_name: str) -> dict:
    owner_name = lead.get("owner_name") or ""
    first = owner_name.split()[0] if owner_name else "there"
    addr = lead.get("property_address") or ""
    street = _street_name(addr)
    yrs = lead.get("years_owned")
    return {
        "owner_first_name": first,
        "owner_full_name": owner_name,
        "property_address": addr or "(address)",
        "street_name": street or "(street)",
        "years_owned": yrs if yrs else "many",
        "sender_name": sender_name,
        "sender_phone": sender_phone,
        "business_name": business_name,
        "tomorrow_day": (datetime.now() + timedelta(days=1)).strftime("%A"),
    }


def _render(s: str, vars_: dict) -> tuple[str, list[str]]:
    missing = []
    out = s
    for m in re.findall(r"\{(\w+)\}", s):
        v = vars_.get(m)
        if v in (None, ""):
            missing.append(m)
        else:
            out = out.replace("{" + m + "}", str(v))
    return out, missing


def _street_name(address: str) -> str:
    if not address:
        return ""
    first = address.split(",")[0].strip()
    parts = first.split()
    if len(parts) >= 3 and parts[0].isdigit():
        return " ".join(parts[1:])
    return first


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    lead = {
        "owner_name": "Jane Doe",
        "property_address": "1234 Elm St, Memphis, TN 38127",
        "years_owned": 27,
    }
    d = compose(lead, archetype="probate", channel="email",
                sender_name="Alex Chen",
                sender_phone="(901) 555-0199",
                business_name="Midsouth Home Partners LLC",
                business_address="123 Main St, Memphis, TN 38103")
    print(f"template: {d['template_id']}")
    print(f"subject:  {d['subject']}")
    print("---")
    print(d["body"])
