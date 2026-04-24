"""
buyer_matching.py
=================

Rank buyers against a lead.  The buyer CRUD itself lives in db.py;
this module is pure logic — fit + reliability scoring.

Usage
-----
    from db import list_buyers
    from buyer_matching import match

    buyers = list_buyers(db, zip_code="38127")
    ranked = match(lead_dict, buyers)   # list of (buyer, score, reasons)
    count = count_matches(lead_dict, buyers)   # for scoring.exit factor
"""

from __future__ import annotations

from typing import Optional


def _fit(buyer: dict, lead: dict, zip_code: str) -> tuple[float, list[str]]:
    """Hard filters first; any miss returns (0, reason).  Then fit bonus."""
    reasons: list[str] = []

    buyer_zips = (buyer.get("zip_codes") or "").split(",")
    buyer_zips = [z.strip() for z in buyer_zips if z.strip()]
    if buyer_zips and zip_code not in buyer_zips:
        return 0, [f"{zip_code} not in buy-box"]

    buyer_types = (buyer.get("property_types") or "SFR").split(",")
    buyer_types = [t.strip().upper() for t in buyer_types]
    lead_type = (lead.get("property_type") or "").upper()
    if lead_type and buyer_types and lead_type not in buyer_types:
        return 0, [f"{lead_type} not in buy-box"]

    if not buyer.get("flood_ok") and lead.get("flood_zone"):
        return 0, ["flood zone"]
    if not buyer.get("hoa_ok") and lead.get("in_hoa"):
        return 0, ["HOA"]

    arv = lead.get("estimated_arv")
    if arv:
        if buyer.get("min_arv") and arv < buyer["min_arv"]:
            return 0, [f"ARV ${arv:,.0f} below min"]
        if buyer.get("max_arv") and arv > buyer["max_arv"]:
            return 0, [f"ARV ${arv:,.0f} above max"]

    if buyer.get("min_beds") and lead.get("bedrooms") is not None:
        if lead["bedrooms"] < buyer["min_beds"]:
            return 0, [f"{lead['bedrooms']} beds < min {buyer['min_beds']}"]

    if buyer.get("min_year_built") and lead.get("year_built"):
        if lead["year_built"] < buyer["min_year_built"]:
            return 0, [f"built {lead['year_built']} < min {buyer['min_year_built']}"]

    repair = lead.get("estimated_repair")
    if repair and arv and buyer.get("max_repair_pct"):
        pct = repair / arv
        if pct > buyer["max_repair_pct"]:
            return 0, [f"repair {pct:.0%} > {buyer['max_repair_pct']:.0%} limit"]
        if pct < buyer["max_repair_pct"] * 0.6:
            reasons.append("light rehab")

    # ARV sweet-spot bonus
    fit = 60.0   # base score for passing all hard filters
    if arv and buyer.get("min_arv") and buyer.get("max_arv"):
        mid = (buyer["min_arv"] + buyer["max_arv"]) / 2
        half = (buyer["max_arv"] - buyer["min_arv"]) / 2
        if half > 0:
            offset = abs(arv - mid) / half
            fit += (1 - offset) * 30
            if offset < 0.3:
                reasons.append("ARV in sweet spot")

    # Rehab-tolerance bonus
    if "light rehab" in reasons:
        fit += 10

    return min(fit, 100), reasons


def _reliability(buyer: dict) -> tuple[float, list[str]]:
    offers = buyer.get("offers_sent") or 0
    closed = buyer.get("deals_closed") or 0
    fell = buyer.get("deals_fell_through") or 0

    if offers == 0:
        return 50.0, ["no track record"]

    close_rate = closed / offers
    fall_rate = fell / max(closed + fell, 1)
    score = 40 + close_rate * 70 - fall_rate * 40
    reasons = []
    if closed >= 3:
        score += 10
        reasons.append(f"{closed} closed")
    if fall_rate > 0.3:
        reasons.append(f"{fall_rate:.0%} fall-through")
    return max(0, min(score, 100)), reasons


def match(lead: dict, buyers: list[dict],
          zip_code: Optional[str] = None,
          min_fit: float = 50) -> list[tuple[dict, float, list[str]]]:
    """
    Return (buyer, combined_rank, reasons) tuples sorted best-first.
    Combined rank = 70% fit + 30% reliability.
    """
    zip_ = zip_code or lead.get("zip_code") or ""
    results = []
    for b in buyers:
        fit_score, fit_reasons = _fit(b, lead, zip_)
        if fit_score < min_fit:
            continue
        rel_score, rel_reasons = _reliability(b)
        combined = fit_score * 0.7 + rel_score * 0.3
        results.append((b, combined, fit_reasons + rel_reasons))
    results.sort(key=lambda r: r[1], reverse=True)
    return results


def count_matches(lead: dict, buyers: list[dict],
                  zip_code: Optional[str] = None,
                  min_fit: float = 60) -> int:
    """Used by scoring to populate the exit factor."""
    return len(match(lead, buyers, zip_code, min_fit))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    buyers = [
        {
            "name": "Mid-South Rental Fund LLC",
            "zip_codes": "38127,38109,38118,38115",
            "property_types": "SFR",
            "min_arv": 55000, "max_arv": 140000,
            "max_repair_pct": 0.30, "min_beds": 2, "min_year_built": 1950,
            "offers_sent": 4, "deals_closed": 2, "deals_fell_through": 0,
        },
        {
            "name": "Dana Ellis",
            "zip_codes": "38128,38114,38111",
            "property_types": "SFR",
            "min_arv": 100000, "max_arv": 220000,
            "max_repair_pct": 0.40, "min_beds": 3,
            "offers_sent": 2, "deals_closed": 1, "deals_fell_through": 0,
        },
        {
            "name": "Robert Khan Holdings",
            "zip_codes": "38127,38109",
            "property_types": "SFR",
            "min_arv": 40000, "max_arv": 95000,
            "max_repair_pct": 0.25, "min_beds": 2,
            "offers_sent": 0, "deals_closed": 0, "deals_fell_through": 0,
        },
    ]

    lead = {
        "zip_code": "38127",
        "property_type": "SFR",
        "estimated_arv": 135000,
        "estimated_repair": 22000,
        "bedrooms": 3, "bathrooms": 1.5, "year_built": 1962,
    }
    print("Lead: 1234 Elm St, 38127, $135k ARV, $22k rehab")
    for buyer, rank, reasons in match(lead, buyers):
        print(f"  {rank:>5.1f}  {buyer['name']}")
        for r in reasons:
            print(f"         · {r}")
    print(f"\ncount_matches -> {count_matches(lead, buyers)}")
