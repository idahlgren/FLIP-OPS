"""
End-to-end integration test — exercises all five modules together.
"""

import os
import tempfile
import csv

import db as db_module
from propstream_import import import_file
from buyer_matching import match, count_matches
from templates import compose
from scoring import score_lead, detect_archetype


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_path = tempfile.mktemp(suffix=".db")
conn = db_module.connect(db_path)
db_module.init_schema(conn)

# Seed buyer list
buyer_data = [
    {"name": "Mid-South Rental Fund LLC", "entity_type": "LLC",
     "primary_contact": "Jacob Patel", "email": "jacob@midsouth.com",
     "zip_codes": "38127,38109,38118,38115",
     "min_arv": 55000, "max_arv": 140000,
     "max_repair_pct": 0.30, "min_beds": 2, "min_year_built": 1950,
     "pof_on_file": 1, "pof_amount": 400000,
     "offers_sent": 4, "deals_closed": 2},
    {"name": "Dana Ellis", "entity_type": "Individual",
     "zip_codes": "38128,38114,38111",
     "min_arv": 100000, "max_arv": 220000,
     "max_repair_pct": 0.40, "min_beds": 3,
     "pof_on_file": 1, "pof_amount": 180000,
     "offers_sent": 2, "deals_closed": 1},
    {"name": "Robert Khan Holdings", "entity_type": "LLC",
     "zip_codes": "38127,38109",
     "min_arv": 40000, "max_arv": 95000,
     "max_repair_pct": 0.25, "min_beds": 2,
     "pof_on_file": 0,
     "offers_sent": 0, "deals_closed": 0},
]
for b in buyer_data:
    db_module.insert_buyer(conn, b)

print(f"Seeded {len(db_module.list_buyers(conn))} buyers\n")


# ---------------------------------------------------------------------------
# Create a PropStream-style CSV
# ---------------------------------------------------------------------------

csv_rows = [
    {"Property Address": "1234 Elm St", "Property City": "Memphis",
     "Property State": "TN", "Property Zip": "38127",
     "Owner 1 First Name": "Jane", "Owner 1 Last Name": "Doe",
     "Mailing Address": "5678 Oak Rd", "Mailing City": "Atlanta",
     "Mailing State": "GA", "Mailing Zip": "30301",
     "Estimated Value": "$135,000", "Open Mortgage Balance": "$0",
     "Probate": "Yes", "Vacant": "Yes", "Absentee Owner": "Yes",
     "Years Owned": "27", "Bedrooms": "3", "Bathrooms": "1.5",
     "Building Area": "1240", "Year Built": "1962",
     "Property Type": "Single Family", "Phone 1": "(901) 555-1234",
     "Email": "jane@email.com", "List Name": "38127 probate"},
    {"Property Address": "3144 Brookmeade", "Property City": "Memphis",
     "Property State": "TN", "Property Zip": "38128",
     "Owner 1 First Name": "James", "Owner 1 Last Name": "Park",
     "Owner 2 First Name": "Linda", "Owner 2 Last Name": "Park",
     "Estimated Value": "$168,000", "Open Mortgage Balance": "$42,000",
     "Divorce": "Yes", "Years Owned": "18",
     "Bedrooms": "3", "Bathrooms": "2", "Building Area": "1680",
     "Year Built": "1975", "Property Type": "Single Family",
     "Phone 1": "(901) 555-7733"},
]

csv_path = tempfile.mktemp(suffix=".csv")
headers = sorted({k for r in csv_rows for k in r.keys()})
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=headers)
    w.writeheader()
    for r in csv_rows:
        row = dict.fromkeys(headers, "")
        row.update(r)
        w.writerow(row)


# ---------------------------------------------------------------------------
# Import with buyer enrichment
# ---------------------------------------------------------------------------

def enrich(lead_dict):
    buyers = db_module.list_buyers(conn, zip_code=lead_dict.get("zip_code"))
    return count_matches(lead_dict, buyers)

result = import_file(conn, csv_path,
                     score_threshold=70.0,
                     matching_buyers_fn=enrich)

print(f"Import: {result.imported} imported, {result.rejected} rejected\n")


# ---------------------------------------------------------------------------
# For each imported lead, show: score breakdown, buyer matches, draft
# ---------------------------------------------------------------------------

for lead_id in result.inserted_ids:
    lead = db_module.get_lead(conn, lead_id)
    print("=" * 66)
    print(f"{lead['property_address']}  —  score {lead['score']}%")
    print("=" * 66)

    # Re-score to show the three-factor breakdown (same inputs, prettier output)
    buyers = db_module.list_buyers(conn, zip_code=lead["zip_code"])
    n_buyers = count_matches(lead, buyers)
    s = score_lead(lead, matching_buyers=n_buyers)

    for name, f in s["factors"].items():
        bar = "█" * int(f["score"] / 5)
        print(f"  {name:<12} {f['score']:>5.1f}%  [{bar:<20}]  "
              f"weight {f['weight']:.0%}")

    print(f"\nArchetype: {lead['archetype']}")
    print(f"Stage:     {lead['stage']}")

    # Top buyer matches
    print("\nTop buyer matches:")
    for b, rank, reasons in match(lead, buyers)[:3]:
        print(f"  {rank:>5.1f}  {b['name']}")
        for r in reasons:
            print(f"         · {r}")

    # Draft outreach
    print("\nDraft outreach (email):")
    draft = compose(lead, archetype=lead["archetype"], channel="email",
                    sender_name="Alex Chen",
                    sender_phone="(901) 555-0199",
                    business_name="Midsouth Home Partners LLC",
                    business_address="123 Main St, Memphis, TN 38103")
    print(f"  template: {draft['template_id']}")
    print(f"  subject:  {draft['subject']}")

    # Log the outbound in the message table
    db_module.log_message(conn, lead_id=lead_id, direction="outbound",
                          channel="email", subject=draft["subject"],
                          body=draft["body"],
                          template_id=draft["template_id"])

    # Simulate an inbound reply
    db_module.log_message(conn, lead_id=lead_id, direction="inbound",
                          channel="email",
                          body="Maybe — what price were you thinking?")

    # Show message log
    print("\nMessage chain:")
    for m in db_module.get_messages(conn, lead_id):
        arrow = "→" if m["direction"] == "outbound" else "←"
        print(f"  {arrow} {m['channel']:<5}  "
              f"{(m['subject'] or m['body'])[:50]}...")

    final = db_module.get_lead(conn, lead_id)
    print(f"\nStage after reply: {final['stage']}")

    print()


# ---------------------------------------------------------------------------
# Queue view
# ---------------------------------------------------------------------------

print("=" * 66)
print("QUEUE")
print("=" * 66)
print(f"Counts by stage: {db_module.queue_counts(conn)}\n")
for lead in db_module.list_leads(conn, min_score=70):
    print(f"  {lead['score']:>5.1f}%  {lead['property_address']:<45} "
          f"{lead['stage']}")


# Cleanup
os.remove(csv_path)
os.remove(db_path)
