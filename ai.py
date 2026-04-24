"""
ai.py
=====

Claude-powered intelligence layer for the wholesale tool.

Features
--------
  score_lead_ai()      — LLM-augmented lead scoring
  analyze_lead()       — contextual summary for the detail page
  suggest_actions()    — next-step recommendations from conversation history
  personalize_draft()  — tailor outreach templates to the lead
  detect_archetype_ai() — smarter archetype classification

All functions are non-blocking on missing API key — they return sensible
fallbacks so the app works without Claude configured.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import anthropic


MODEL = "claude-sonnet-4-6"


def _parse_json(text: str) -> dict | list:
    """Extract JSON from a response that may be wrapped in markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # Find the JSON object or array
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        if start_char in text:
            start = text.index(start_char)
            end = text.rindex(end_char) + 1
            return json.loads(text[start:end])
    return json.loads(text)


def _client() -> Optional[anthropic.Anthropic]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _lead_context(lead: dict) -> str:
    """Build a text summary of a lead for prompts."""
    lines = [
        f"Property: {lead.get('property_address', 'unknown')}",
        f"Owner: {lead.get('owner_name', 'unknown')}",
    ]
    if lead.get("owner_name_2"):
        lines.append(f"Co-owner: {lead['owner_name_2']}")
    if lead.get("owner_phone"):
        lines.append(f"Phone: {lead['owner_phone']}")
    if lead.get("owner_email"):
        lines.append(f"Email: {lead['owner_email']}")
    if lead.get("owner_mailing"):
        lines.append(f"Mailing address: {lead['owner_mailing']}")

    lines.append(f"ARV: ${lead.get('estimated_arv') or 0:,.0f}")
    lines.append(f"Estimated repair: ${lead.get('estimated_repair') or 0:,.0f}")
    lines.append(f"Mortgage balance: ${lead.get('mortgage_balance') or 0:,.0f}")
    if lead.get("free_and_clear"):
        lines.append("Free and clear: YES")
    lines.append(f"Beds/baths: {lead.get('bedrooms', '?')}/{lead.get('bathrooms', '?')}")
    lines.append(f"Sqft: {lead.get('square_feet', '?')}")
    lines.append(f"Year built: {lead.get('year_built', '?')}")
    lines.append(f"Property type: {lead.get('property_type', '?')}")
    lines.append(f"Years owned: {lead.get('years_owned', '?')}")

    signals = []
    if lead.get("pre_foreclosure"):
        signals.append("pre-foreclosure")
    if lead.get("tax_delinquent_yrs"):
        signals.append(f"tax delinquent ({lead['tax_delinquent_yrs']} yrs)")
    if lead.get("probate"):
        signals.append("probate")
    if lead.get("vacant"):
        signals.append("vacant")
    if lead.get("divorce"):
        signals.append("divorce")
    if lead.get("bankruptcy"):
        signals.append("bankruptcy")
    if lead.get("absentee_miles"):
        signals.append(f"absentee owner ({lead['absentee_miles']} miles)")
    if lead.get("code_violations"):
        signals.append(f"code violations ({lead['code_violations']})")
    if lead.get("evictions_12mo"):
        signals.append(f"evictions last 12mo ({lead['evictions_12mo']})")
    if lead.get("expired_listing_days"):
        signals.append(f"expired listing ({lead['expired_listing_days']} days ago)")
    if signals:
        lines.append(f"Motivation signals: {', '.join(signals)}")
    else:
        lines.append("Motivation signals: none detected")

    lines.append(f"Current stage: {lead.get('stage', 'new')}")
    if lead.get("seller_asking"):
        lines.append(f"Seller asking: ${lead['seller_asking']:,.0f}")
    if lead.get("source_list"):
        lines.append(f"Source list: {lead['source_list']}")
    if lead.get("notes"):
        lines.append(f"Notes: {lead['notes']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. LLM-augmented lead scoring
# ---------------------------------------------------------------------------

def score_lead_ai(lead: dict, deterministic_score: dict,
                  matching_buyers: int = 0) -> Optional[dict]:
    """
    Augment the deterministic score with Claude's analysis.
    Returns dict with ai_score, ai_confidence, ai_reasoning, and
    adjusted_total — or None if Claude is unavailable.
    """
    client = _client()
    if not client:
        return None

    context = _lead_context(lead)
    det = deterministic_score

    prompt = f"""You are a wholesale real estate deal analyst in Memphis, TN.

SCORING SYSTEM:
- Motivation (30%): Will the seller accept a below-market offer? Signals: pre-foreclosure, tax delinquency, probate, divorce, vacancy, absentee ownership, code violations, long ownership, evictions, bankruptcy, expired listings.
- Economics (50%): Does the deal math work? Consider equity position, ARV vs mortgage vs repair costs, MAO (max allowable offer = ARV × 0.80 - repairs - 20% wholesale fee), and buyer demand.
- Workability (20%): Can you close? SFR preferred, 900-2200 sqft, built 1945-1995, 2-4 beds, reachable owner, single owner easier.

TIER THRESHOLDS:
- A (85%+): Work immediately — top of queue
- B (70-84%): Work today, skip-trace, call within 24h
- C (55-69%): Queue for follow-up, drip campaign
- D (40-54%): Low priority, mail only
- Skip (<40%): Drop, not a deal

LEAD DATA:
{context}

DETERMINISTIC SCORES:
- Motivation: {det['factors']['motivation']['score']}/100 (confidence: {det['factors']['motivation']['confidence']}%)
- Economics: {det['factors']['economics']['score']}/100 (confidence: {det['factors']['economics']['confidence']}%)
- Workability: {det['factors']['workability']['score']}/100 (confidence: {det['factors']['workability']['confidence']}%)
- Total: {det['total']}% (confidence: {det['confidence']}%)
- Tier: {det['tier']}

Matching buyers in network: {matching_buyers}

Analyze this lead. Consider factors the formula might miss:
- Stacking of multiple motivation signals (compound distress)
- Local Memphis market context
- Whether the owner's situation suggests urgency
- Red flags the formula doesn't capture

You MUST respond with ONLY a JSON object, no markdown, no explanation:
{{"ai_score": <0-100 number>, "ai_confidence": <0-100 number>, "ai_tier": "<A/B/C/D/skip>", "reasoning": "<2-3 sentence analysis>", "flags": ["<any red flags or opportunities the formula missed>"]}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        result = _parse_json(text)

        # Blend: 60% deterministic, 40% AI
        adjusted = det["total"] * 0.6 + result["ai_score"] * 0.4
        result["adjusted_total"] = round(adjusted, 1)
        result["deterministic_total"] = det["total"]
        return result
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. Lead analysis / summary
# ---------------------------------------------------------------------------

def analyze_lead(lead: dict, messages: list[dict] = None,
                 buyer_matches: int = 0) -> Optional[str]:
    """Generate a contextual analysis summary for the lead detail page."""
    client = _client()
    if not client:
        return None

    context = _lead_context(lead)

    convo = ""
    if messages:
        convo_lines = []
        for m in messages[-6:]:  # last 6 messages
            direction = "OUT" if m["direction"] == "outbound" else "IN"
            body = (m.get("body") or "")[:200]
            convo_lines.append(f"[{direction}] {body}")
        convo = "\nCONVERSATION HISTORY:\n" + "\n".join(convo_lines)

    prompt = f"""You are a wholesale real estate analyst in Memphis, TN. Write a brief tactical analysis of this lead for the operator.

LEAD DATA:
{context}

Matching buyers: {buyer_matches}
{convo}

Write 2-4 sentences. Be direct and specific — what makes this deal worth pursuing or not, what's the angle, what should the operator know. No fluff. Talk like a wholesaler, not a professor."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 3. Next action suggestions
# ---------------------------------------------------------------------------

def suggest_actions(lead: dict, messages: list[dict] = None) -> Optional[list[str]]:
    """Suggest 2-3 next actions based on lead state and conversation."""
    client = _client()
    if not client:
        return None

    context = _lead_context(lead)

    convo = ""
    if messages:
        convo_lines = []
        for m in messages[-6:]:
            direction = "OUT" if m["direction"] == "outbound" else "IN"
            body = (m.get("body") or "")[:200]
            convo_lines.append(f"[{direction}] {body}")
        convo = "\nCONVERSATION HISTORY:\n" + "\n".join(convo_lines)

    prompt = f"""You are a Memphis wholesale real estate operator. Based on this lead's current state, suggest the 2-3 most important next actions.

LEAD DATA:
{context}
{convo}

Respond in JSON only — an array of 2-3 short action strings (one sentence each, imperative voice):
["action 1", "action 2", "action 3"]"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return _parse_json(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 4. Draft personalization
# ---------------------------------------------------------------------------

def personalize_draft(lead: dict, draft_body: str, draft_subject: str = None,
                      channel: str = "email") -> Optional[dict]:
    """Personalize a template-generated draft for the specific lead."""
    client = _client()
    if not client:
        return None

    context = _lead_context(lead)

    prompt = f"""You are writing outreach for a Memphis wholesale real estate buyer. You have a template-generated draft that needs to be personalized for this specific lead.

LEAD DATA:
{context}

CHANNEL: {channel}

CURRENT DRAFT SUBJECT: {draft_subject or '(none)'}
CURRENT DRAFT BODY:
{draft_body}

Rewrite the draft to feel more personal and specific to this owner's situation. Rules:
- Keep the same tone and length (don't make it longer)
- Reference specific details about their situation naturally
- Don't be salesy or pushy
- Keep compliance footers exactly as they are
- For call scripts, keep the structure (OPENER/QUESTIONS/DO NOT) but personalize the talking points

Respond in JSON only:
{{"subject": "<personalized subject or null if no subject>", "body": "<personalized body>"}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return _parse_json(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 5. Smarter archetype detection
# ---------------------------------------------------------------------------

def detect_archetype_ai(lead: dict) -> Optional[str]:
    """Use Claude to classify the lead into an archetype."""
    client = _client()
    if not client:
        return None

    context = _lead_context(lead)

    prompt = f"""Classify this wholesale real estate lead into exactly one archetype.

LEAD DATA:
{context}

ARCHETYPES (pick one):
- probate: inherited property, estate situation
- pre_foreclosure: facing foreclosure, NOD filed, behind on payments
- tired_landlord: long-term owner with tenant issues, evictions, wants out
- tax_delinquent: behind on property taxes 2+ years
- vacant_distressed: vacant property with code violations or visible neglect
- expired_listing: was listed but didn't sell, owner may be frustrated
- divorce: property tied to divorce proceedings
- general: none of the above clearly applies

Respond with just the archetype name, nothing else."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip().lower()
        valid = ("probate", "pre_foreclosure", "tired_landlord",
                 "tax_delinquent", "vacant_distressed", "expired_listing",
                 "divorce", "general")
        return text if text in valid else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    lead = {
        "property_address": "1234 Elm St, Memphis, TN 38127",
        "owner_name": "Jane Doe",
        "owner_phone": "+19015551234",
        "owner_email": "jane@email.com",
        "owner_mailing": "5678 Oak Rd, Atlanta, GA 30301",
        "estimated_arv": 135000,
        "estimated_repair": 27000,
        "mortgage_balance": 0,
        "free_and_clear": 1,
        "square_feet": 1240,
        "year_built": 1962,
        "bedrooms": 3,
        "bathrooms": 1.5,
        "property_type": "SFR",
        "probate": 1,
        "vacant": 1,
        "absentee_miles": 500,
        "years_owned": 27,
        "code_violations": 1,
        "stage": "new",
        "source_list": "38127 probate + absentee",
    }

    from scoring import score_lead
    det = score_lead(lead, matching_buyers=2)

    print("=== AI Score ===")
    result = score_lead_ai(lead, det, matching_buyers=2)
    if result:
        print(f"  Deterministic: {result['deterministic_total']}%")
        print(f"  AI score: {result['ai_score']}%")
        print(f"  Adjusted: {result['adjusted_total']}%")
        print(f"  Tier: {result['ai_tier']}")
        print(f"  Reasoning: {result['reasoning']}")
        if result.get("flags"):
            print(f"  Flags: {', '.join(result['flags'])}")
    else:
        print("  (unavailable)")

    print("\n=== Analysis ===")
    analysis = analyze_lead(lead, buyer_matches=2)
    print(f"  {analysis or '(unavailable)'}")

    print("\n=== Next Actions ===")
    actions = suggest_actions(lead)
    if actions:
        for a in actions:
            print(f"  - {a}")
    else:
        print("  (unavailable)")

    print("\n=== Archetype ===")
    arch = detect_archetype_ai(lead)
    print(f"  {arch or '(unavailable)'}")
