"""
propstream_import.py
====================

Import PropStream CSV exports into the leads table.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import db as db_module
from scoring import score_lead, detect_archetype


FIELD_MAP = {
    "Property Address":          "prop_address_line",
    "Property Street Address":   "prop_address_line",
    "Property City":             "prop_city",
    "Property State":            "prop_state",
    "Property Zip":              "zip_code",
    "Property Zip Code":         "zip_code",
    "APN":                       "parcel_id",
    "Parcel ID":                 "parcel_id",

    "Owner 1 First Name":        "_o1_first",
    "Owner 1 Last Name":         "_o1_last",
    "Owner 2 First Name":        "_o2_first",
    "Owner 2 Last Name":         "_o2_last",
    "Mailing Address":           "_mail_line",
    "Mailing Street Address":    "_mail_line",
    "Mailing City":              "_mail_city",
    "Mailing State":             "_mail_state",
    "Mailing Zip":               "_mail_zip",

    "Estimated Value":           "estimated_arv",
    "AVM":                       "estimated_arv",
    "Open Mortgage Balance":     "mortgage_balance",
    "Total Open Loan Balance":   "mortgage_balance",

    "Estimated Repair Cost":     "estimated_repair",
    "Estimated Rehab":           "estimated_repair",
    "Est. Rehab":                "estimated_repair",

    "Bedrooms":                  "bedrooms",
    "Bathrooms":                 "bathrooms",
    "Building Area":             "square_feet",
    "Living Sq Ft":              "square_feet",
    "Year Built":                "year_built",
    "Property Type":             "property_type",
    "Land Use":                  "property_type",

    "Pre-Foreclosure":           "pre_foreclosure",
    "Preforeclosure":            "pre_foreclosure",
    "Notice of Default":         "pre_foreclosure",
    "Auction":                   "pre_foreclosure",
    "Tax Delinquent":            "_tax_flag",
    "Years Behind on Taxes":     "tax_delinquent_yrs",
    "Tax Years Delinquent":      "tax_delinquent_yrs",
    "Probate":                   "probate",
    "Vacant":                    "vacant",
    "Vacancy":                   "vacant",
    "Absentee Owner":            "_abs_flag",
    "Divorce":                   "divorce",
    "Bankruptcy":                "bankruptcy",
    "Code Violation":            "_cv_flag",
    "Eviction":                  "_ev_flag",
    "Ownership Length (months)": "_ownership_months",
    "Years Owned":               "years_owned",
    "Length of Residence":       "years_owned",
    "Last Listed Date":          "_last_listed",

    "Phone 1":                   "_phone1",
    "Phone 2":                   "_phone2",
    "Mobile Phone":              "_phone_mobile",
    "Email":                     "_email1",
    "Email 1":                   "_email1",

    "List Name":                 "source_list",

    # PropStream v2 export format
    "Address":                              "prop_address_line",
    "City":                                 "prop_city",
    "State":                                "prop_state",
    "Zip":                                  "zip_code",
    "Est. Value":                           "estimated_arv",
    "Est. Remaining balance of Open Loans": "mortgage_balance",
    "Building Sqft":                        "square_feet",
    "Total Bathrooms":                      "bathrooms",
    "Effective Year Built":                 "year_built",
    "Foreclosure Factor":                   "_foreclosure_factor",
    "Owner Occupied":                       "_owner_occupied",
    "Do Not Mail":                          "_do_not_mail",
    "Lien Amount":                          "_lien_amount",
}

TRUE_VALS = {"yes", "y", "true", "1", "x", "t"}


def _bool(v) -> Optional[int]:
    if v is None or v == "":
        return None
    return 1 if str(v).strip().lower() in TRUE_VALS else 0


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)))
    except (ValueError, TypeError):
        return None


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def _days_since(v) -> Optional[int]:
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return (datetime.now() - datetime.strptime(str(v).strip(), fmt)).days
        except ValueError:
            continue
    return None


def _normalize_phone(s: str) -> str:
    d = re.sub(r"[^\d]", "", s)
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d.startswith("1"):
        return f"+{d}"
    return s


def _norm_type(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    low = s.lower()
    if any(k in low for k in ("single family", "sfr", "sfh", "residential")):
        return "SFR"
    if "condo" in low:
        return "condo"
    if "mobile" in low or "manufactured" in low:
        return "MH"
    return s


def parse_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {}
            for header, value in raw.items():
                if header is None or value in (None, ""):
                    continue
                key = FIELD_MAP.get(header.strip())
                if key:
                    row[key] = value.strip()
            if row.get("prop_address_line"):
                rows.append(row)
    return rows


def normalize_row(row: dict) -> dict:
    addr_parts = [row.get("prop_address_line"), row.get("prop_city"),
                  row.get("prop_state"), row.get("zip_code")]
    property_address = ", ".join(p for p in addr_parts if p)

    owner_name = " ".join(p for p in (row.get("_o1_first"),
                                      row.get("_o1_last")) if p) or None
    owner_name_2 = " ".join(p for p in (row.get("_o2_first"),
                                        row.get("_o2_last")) if p) or None

    mail_parts = [row.get("_mail_line"), row.get("_mail_city"),
                  row.get("_mail_state"), row.get("_mail_zip")]
    owner_mailing = ", ".join(p for p in mail_parts if p) or None

    phone = (row.get("_phone_mobile") or row.get("_phone1")
             or row.get("_phone2"))
    owner_phone = _normalize_phone(phone) if phone else None
    owner_email = row.get("_email1")

    arv = _num(row.get("estimated_arv"))
    mortgage = _num(row.get("mortgage_balance")) or 0
    free_and_clear = 1 if (arv and arv > 0 and mortgage == 0) else 0
    repair = _num(row.get("estimated_repair"))
    if repair is None and arv:
        repair = arv * 0.15

    pre_fc = _bool(row.get("pre_foreclosure"))
    tax_yrs = _int(row.get("tax_delinquent_yrs"))
    if tax_yrs is None and _bool(row.get("_tax_flag")):
        tax_yrs = 1

    absentee_miles = None
    if _bool(row.get("_abs_flag")):
        ms = row.get("_mail_state")
        ps = row.get("prop_state")
        absentee_miles = 500 if (ms and ps and ms != ps) else 150

    years_owned = _int(row.get("years_owned"))
    if years_owned is None and row.get("_ownership_months"):
        m = _int(row["_ownership_months"])
        if m:
            years_owned = m // 12

    return {
        "property_address": property_address,
        "zip_code": row.get("zip_code"),
        "parcel_id": row.get("parcel_id"),
        "owner_name": owner_name,
        "owner_name_2": owner_name_2,
        "owner_phone": owner_phone,
        "owner_email": owner_email,
        "owner_mailing": owner_mailing,
        "estimated_arv": arv,
        "estimated_repair": repair,
        "mortgage_balance": mortgage,
        "free_and_clear": free_and_clear,
        "square_feet": _int(row.get("square_feet")),
        "year_built": _int(row.get("year_built")),
        "bedrooms": _int(row.get("bedrooms")),
        "bathrooms": _num(row.get("bathrooms")),
        "property_type": _norm_type(row.get("property_type")),
        "pre_foreclosure": pre_fc,
        "tax_delinquent_yrs": tax_yrs,
        "probate": _bool(row.get("probate")),
        "vacant": _bool(row.get("vacant")),
        "absentee_miles": absentee_miles,
        "years_owned": years_owned,
        "code_violations": 1 if _bool(row.get("_cv_flag")) else 0,
        "evictions_12mo": 1 if _bool(row.get("_ev_flag")) else 0,
        "divorce": _bool(row.get("divorce")),
        "bankruptcy": _bool(row.get("bankruptcy")),
        "expired_listing_days": _days_since(row.get("_last_listed")),
        "source_list": row.get("source_list"),
    }


@dataclass
class ImportResult:
    total: int
    imported: int
    rejected: int
    rejections: list[dict]
    inserted_ids: list[str]


def import_file(conn: sqlite3.Connection, path: str, *,
                score_threshold: float = 70.0,
                matching_buyers_fn=None) -> ImportResult:
    """
    Parse CSV, score every row, insert rows >= score_threshold.

    matching_buyers_fn: optional (lead_dict) -> int returning buyer-match
    count.  Without it, exit score is 0 and scores run low.
    """
    parsed = parse_csv(path)
    result = ImportResult(total=len(parsed), imported=0, rejected=0,
                          rejections=[], inserted_ids=[])

    for raw in parsed:
        try:
            lead_dict = normalize_row(raw)
        except Exception as e:
            result.rejected += 1
            result.rejections.append({
                "address": raw.get("prop_address_line"),
                "score": None, "reason": f"parse_error: {e}",
            })
            continue

        bm = matching_buyers_fn(lead_dict) if matching_buyers_fn else None
        s = score_lead(lead_dict, matching_buyers=bm)

        if s["total"] < score_threshold:
            result.rejected += 1
            result.rejections.append({
                "address": lead_dict["property_address"],
                "score": s["total"],
                "reason": f"below {score_threshold}",
            })
            continue

        lead_dict["score"] = s["total"]
        lead_dict["score_confidence"] = s["confidence"]
        lead_dict["archetype"] = detect_archetype(lead_dict)

        lead_id = db_module.insert_lead(conn, lead_dict)
        result.imported += 1
        result.inserted_ids.append(lead_id)

    return result


if __name__ == "__main__":
    import os
    import tempfile

    sample_rows = [
        {
            "Property Address": "1234 Elm St", "Property City": "Memphis",
            "Property State": "TN", "Property Zip": "38127",
            "APN": "012345-00001",
            "Owner 1 First Name": "Jane", "Owner 1 Last Name": "Doe",
            "Mailing Address": "5678 Oak Rd", "Mailing City": "Atlanta",
            "Mailing State": "GA", "Mailing Zip": "30301",
            "Estimated Value": "$135,000", "Open Mortgage Balance": "$0",
            "Probate": "Yes", "Vacant": "Yes", "Absentee Owner": "Yes",
            "Years Owned": "27", "Bedrooms": "3", "Bathrooms": "1.5",
            "Building Area": "1240", "Year Built": "1962",
            "Property Type": "Single Family Residence",
            "Phone 1": "(901) 555-1234", "Email": "jane@email.com",
            "List Name": "38127 probate + absentee",
        },
        {
            "Property Address": "4021 Barron Ave", "Property City": "Memphis",
            "Property State": "TN", "Property Zip": "38109",
            "APN": "029876-00042",
            "Owner 1 First Name": "Robert", "Owner 1 Last Name": "Hayes",
            "Mailing Address": "4021 Barron Ave", "Mailing City": "Memphis",
            "Mailing State": "TN", "Mailing Zip": "38109",
            "Estimated Value": "$92,000", "Open Mortgage Balance": "$28,500",
            "Pre-Foreclosure": "Yes", "Years Owned": "22",
            "Bedrooms": "3", "Bathrooms": "1", "Building Area": "1105",
            "Year Built": "1958", "Property Type": "Single Family Residence",
            "Phone 1": "(901) 555-9988",
        },
        {
            "Property Address": "999 Overpriced Ln", "Property City": "Memphis",
            "Property State": "TN", "Property Zip": "38117",
            "Owner 1 First Name": "Alan", "Owner 1 Last Name": "Smith",
            "Estimated Value": "$310,000", "Open Mortgage Balance": "$265,000",
            "Bedrooms": "4", "Bathrooms": "2", "Building Area": "1800",
            "Year Built": "1992", "Property Type": "Single Family Residence",
        },
    ]

    headers = sorted({k for r in sample_rows for k in r.keys()})
    csv_path = tempfile.mktemp(suffix=".csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in sample_rows:
            row = dict.fromkeys(headers, "")
            row.update(r)
            w.writerow(row)

    db_path = tempfile.mktemp(suffix=".db")
    conn = db_module.connect(db_path)
    db_module.init_schema(conn)

    result = import_file(conn, csv_path, score_threshold=70.0)

    print(f"Total parsed:   {result.total}")
    print(f"Imported:       {result.imported}")
    print(f"Rejected:       {result.rejected}\n")

    print("IMPORTED:")
    for lead in db_module.list_leads(conn):
        print(f"  {lead['score']:>5.1f}%  {lead['property_address']}")
        print(f"         archetype: {lead['archetype']}  stage: {lead['stage']}")

    print("\nREJECTED:")
    for r in result.rejections:
        s = f"{r['score']}%" if r["score"] is not None else "n/a"
        print(f"  {s:>6}  {r['address']}  ({r['reason']})")

    os.remove(csv_path)
    os.remove(db_path)
