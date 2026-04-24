"""
scoring.py
==========

Three-factor lead scoring.  Simpler than the previous six-factor version;
the underlying math is equivalent but collapsed into three user-facing
buckets that a human can hold in their head.

Factors
-------
  motivation   (30%)  — will the seller accept a low offer
  economics    (50%)  — does the math work (equity + MAO + buyer demand)
  workability  (20%)  — can you actually close (property fit + accessibility)

Output
------
  total        0–100 percentage
  confidence   0–100 percentage (how much data backed the score)
  factors      three-element breakdown for display
  tier         A / B / C / D / skip / unknown
  action       one-line recommendation

Input
-----
  A dict matching the `leads` table columns (see db.py).  We accept a dict
  rather than a typed LeadData object so scoring works directly on rows
  fetched from the database.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Weights (sum to 1.0) and tuning constants
# ---------------------------------------------------------------------------

WEIGHTS = {"motivation": 0.30, "economics": 0.50, "workability": 0.20}

TARGET_FEE_PCT = 0.20              # 20% of end-buyer price
ARV_DISCOUNT = 0.80                # end buyer pays 80% of ARV minus repairs

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Motivation
# ---------------------------------------------------------------------------

def _motivation(lead: dict) -> tuple[float, float]:
    points = 0.0
    if lead.get("pre_foreclosure"):
        points += 40
    if lead.get("tax_delinquent_yrs"):
        points += min(lead["tax_delinquent_yrs"] * 12, 30)
    if lead.get("probate"):
        points += 30
    if lead.get("divorce"):
        points += 20
    if lead.get("vacant"):
        points += 25
    miles = lead.get("absentee_miles")
    if miles and miles > 100:
        points += 25 if miles >= 500 else 15
    cv = lead.get("code_violations") or 0
    points += min(cv * 10, 25)
    yrs = lead.get("years_owned")
    if yrs and yrs >= 15:
        points += min(10 + (yrs - 15) * 1.5, 20)
    ev = lead.get("evictions_12mo") or 0
    points += min(ev * 12, 25)
    if lead.get("bankruptcy"):
        points += 35
    exp = lead.get("expired_listing_days")
    if exp and 60 <= exp <= 365:
        points += 15

    score = min(points, 100)

    # Confidence: proportion of motivation signals we have explicit data on
    known_keys = ("pre_foreclosure", "tax_delinquent_yrs", "probate", "divorce",
                  "vacant", "absentee_miles", "code_violations", "years_owned",
                  "evictions_12mo", "bankruptcy", "expired_listing_days")
    known = sum(1 for k in known_keys if lead.get(k) is not None)
    return score, known / len(known_keys)


# ---------------------------------------------------------------------------
# Economics — merges equity, deal math, and buyer-demand exit
# ---------------------------------------------------------------------------

def _economics(lead: dict, matching_buyers: Optional[int] = None,
               cash_sales_nearby: Optional[int] = None) -> tuple[float, float]:
    arv = lead.get("estimated_arv")
    if not arv or arv <= 0:
        return 0.0, 0.0

    # --- equity component (0-100) ---
    if lead.get("free_and_clear"):
        equity_score = 100.0
    else:
        mortgage = lead.get("mortgage_balance") or 0
        equity_pct = max((arv - mortgage) / arv, 0)
        if equity_pct < 0.30:
            equity_score = equity_pct * 66.67
        elif equity_pct < 0.50:
            equity_score = 20 + (equity_pct - 0.30) * 200
        elif equity_pct < 0.70:
            equity_score = 60 + (equity_pct - 0.50) * 175
        else:
            equity_score = min(95 + (equity_pct - 0.70) * 17, 100)

    # --- deal math component (0-100) ---
    repairs = lead.get("estimated_repair") or arv * 0.15
    buyer_price = arv * ARV_DISCOUNT - repairs
    if buyer_price <= 0:
        deal_score = 0.0
    else:
        mao = buyer_price * (1 - TARGET_FEE_PCT)
        seller = lead.get("seller_asking")
        if seller and seller > 0:
            actual_fee_pct = (buyer_price - seller) / buyer_price
            if actual_fee_pct >= TARGET_FEE_PCT * 1.5:
                deal_score = 100
            elif actual_fee_pct >= TARGET_FEE_PCT:
                deal_score = 80 + (actual_fee_pct - TARGET_FEE_PCT) / (TARGET_FEE_PCT * 0.5) * 20
            elif actual_fee_pct >= TARGET_FEE_PCT * 0.5:
                deal_score = 40 + (actual_fee_pct - TARGET_FEE_PCT * 0.5) / (TARGET_FEE_PCT * 0.5) * 40
            elif actual_fee_pct > 0:
                deal_score = 10 + actual_fee_pct / (TARGET_FEE_PCT * 0.5) * 30
            else:
                deal_score = 0
        else:
            mao_pct = mao / arv
            if mao_pct < 0.30:
                deal_score = mao_pct * 100
            elif mao_pct < 0.50:
                deal_score = 30 + (mao_pct - 0.30) * 250
            else:
                deal_score = min(80 + (mao_pct - 0.50) * 100, 100)

    # --- exit component (0-100) ---
    if matching_buyers is None and cash_sales_nearby is None:
        exit_score = 0.0
        exit_known = False
    else:
        buyers = matching_buyers or 0
        sales = cash_sales_nearby or 0
        exit_score = min(buyers * 8, 40) + min(sales * 7.5, 60)
        exit_known = True

    # Merge: equity 30%, deal_math 40%, exit 30% (within the 50% economics slice)
    combined = equity_score * 0.30 + deal_score * 0.40 + exit_score * 0.30

    confidence = 0.33   # equity always scorable from ARV
    if lead.get("mortgage_balance") is not None or lead.get("free_and_clear"):
        confidence += 0.17
    if lead.get("estimated_repair") is not None:
        confidence += 0.16
    if exit_known:
        confidence += 0.34

    return combined, min(confidence, 1.0)


# ---------------------------------------------------------------------------
# Workability — property fit + accessibility
# ---------------------------------------------------------------------------

def _workability(lead: dict) -> tuple[float, float]:
    checks = []  # each 0..1, averaged

    t = lead.get("property_type")
    if t is not None:
        checks.append(1.0 if str(t).upper() in ("SFR", "SINGLE FAMILY") else 0.0)

    sqft = lead.get("square_feet")
    if sqft is not None:
        if 900 <= sqft <= 2200:
            checks.append(1.0)
        elif 800 <= sqft < 900 or 2200 < sqft <= 2500:
            checks.append(0.5)
        else:
            checks.append(0.0)

    yr = lead.get("year_built")
    if yr is not None:
        if 1945 <= yr <= 1995:
            checks.append(1.0)
        elif 1940 <= yr < 1945 or 1995 < yr <= 2005:
            checks.append(0.6)
        else:
            checks.append(0.2)

    beds = lead.get("bedrooms")
    if beds is not None:
        checks.append(1.0 if 2 <= beds <= 4 else 0.3)

    baths = lead.get("bathrooms")
    if baths is not None:
        checks.append(1.0 if 1 <= baths <= 3 else 0.5)

    # Accessibility — reachable + clear-enough title prior
    if lead.get("owner_phone") or lead.get("owner_email"):
        checks.append(1.0)
    else:
        checks.append(0.2)

    # Single owner is easier to contract
    if lead.get("owner_name_2"):
        checks.append(0.7)
    else:
        checks.append(1.0)

    if not checks:
        return 0.0, 0.0
    score = (sum(checks) / len(checks)) * 100
    return score, len(checks) / 7


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

TIER_THRESHOLDS = [
    (85, "A", "Work immediately — top of the queue."),
    (70, "B", "Work today. Skip-trace, call within 24h."),
    (55, "C", "Queue for follow-up. Drip campaign."),
    (40, "D", "Low priority. Mail only."),
    (0,  "skip", "Drop. Not a deal."),
]


def _tier(score: float, confidence: float) -> tuple[str, str]:
    if confidence < 0.30:
        return "unknown", "Gather more data before scoring."
    for threshold, tier, action in TIER_THRESHOLDS:
        if score >= threshold:
            return tier, action
    return "skip", "Drop. Not a deal."


def score_lead(lead: dict, *,
               matching_buyers: Optional[int] = None,
               cash_sales_nearby: Optional[int] = None) -> dict:
    """
    Score a lead dict.  `matching_buyers` and `cash_sales_nearby` are
    passed separately because they come from other modules (buyers.py
    and the comp tool), not from the lead row itself.

    Returns a flat dict:
      {
        "total": 87.3,
        "confidence": 95,
        "tier": "A",
        "action": "Work immediately...",
        "factors": {
          "motivation":  {"score": 100, "confidence": 83, "weight": 0.30},
          "economics":   {"score": 82,  "confidence": 100, "weight": 0.50},
          "workability": {"score": 95,  "confidence": 100, "weight": 0.20},
        }
      }
    """
    m_score, m_conf = _motivation(lead)
    e_score, e_conf = _economics(lead, matching_buyers, cash_sales_nearby)
    w_score, w_conf = _workability(lead)

    total = (m_score * WEIGHTS["motivation"]
             + e_score * WEIGHTS["economics"]
             + w_score * WEIGHTS["workability"])
    conf = (m_conf * WEIGHTS["motivation"]
            + e_conf * WEIGHTS["economics"]
            + w_conf * WEIGHTS["workability"]) * 100

    tier, action = _tier(total, conf / 100)

    return {
        "total": round(total, 1),
        "confidence": round(conf, 0),
        "tier": tier,
        "action": action,
        "factors": {
            "motivation":  {"score": round(m_score, 1), "confidence": round(m_conf * 100),
                            "weight": WEIGHTS["motivation"]},
            "economics":   {"score": round(e_score, 1), "confidence": round(e_conf * 100),
                            "weight": WEIGHTS["economics"]},
            "workability": {"score": round(w_score, 1), "confidence": round(w_conf * 100),
                            "weight": WEIGHTS["workability"]},
        },
    }


# ---------------------------------------------------------------------------
# Archetype detection (kept, still useful for template selection)
# ---------------------------------------------------------------------------

def detect_archetype(lead: dict) -> str:
    if lead.get("pre_foreclosure"):
        return "pre_foreclosure"
    if lead.get("probate"):
        return "probate"
    if lead.get("evictions_12mo") and (lead.get("years_owned") or 0) >= 10:
        return "tired_landlord"
    if (lead.get("tax_delinquent_yrs") or 0) >= 2:
        return "tax_delinquent"
    if lead.get("vacant") and lead.get("code_violations"):
        return "vacant_distressed"
    exp = lead.get("expired_listing_days")
    if exp and 60 <= exp <= 365:
        return "expired_listing"
    return "general"


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    hot = {
        "probate": 1, "vacant": 1, "absentee_miles": 500,
        "years_owned": 27, "code_violations": 1,
        "estimated_arv": 135000, "mortgage_balance": 0, "free_and_clear": 1,
        "estimated_repair": 27000, "seller_asking": 55000,
        "property_type": "SFR", "square_feet": 1240, "year_built": 1962,
        "bedrooms": 3, "bathrooms": 1.5,
        "owner_phone": "+19015551234", "owner_email": "jane@x.com",
    }
    warm = {
        "tax_delinquent_yrs": 1, "years_owned": 9,
        "estimated_arv": 115000, "mortgage_balance": 68000,
        "estimated_repair": 18000,
        "property_type": "SFR", "square_feet": 1080, "year_built": 1978,
        "bedrooms": 3, "bathrooms": 2,
        "owner_phone": "+19015559999",
    }
    cold = {
        "years_owned": 4,
        "estimated_arv": 140000, "mortgage_balance": 118000,
        "estimated_repair": 8000, "seller_asking": 130000,
        "property_type": "SFR", "square_feet": 1400, "year_built": 1988,
        "bedrooms": 3, "bathrooms": 2,
    }

    for name, lead, bm in [("HOT", hot, 4), ("WARM", warm, 2), ("COLD", cold, 0)]:
        s = score_lead(lead, matching_buyers=bm, cash_sales_nearby=5)
        print(f"\n{name}  total {s['total']}%  conf {s['confidence']}%  "
              f"tier {s['tier']}  ({detect_archetype(lead)})")
        print(f"  {s['action']}")
        for k, v in s["factors"].items():
            bar = "█" * int(v["score"] / 5)
            print(f"    {k:<12} {v['score']:>5.1f}%  [{bar:<20}]  "
                  f"weight {v['weight']:.0%}  conf {v['confidence']}%")
