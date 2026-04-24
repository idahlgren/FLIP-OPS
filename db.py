"""
db.py
=====

Single data layer.  Four tables, straightforward schema, no abstractions
over SQLite.  This replaces the JsonStore pattern, the Channel entity,
the ConsentStatus machinery, and the dataclass-heavy repositories
from the earlier build.

Tables
------
  leads    — one row per property we're pursuing
  buyers   — one row per cash buyer in the network
  messages — one row per outbound or inbound communication
  offers   — one row per (lead, buyer) offer pairing

Everything else (stage counts, stale-lead queries, buyer stats) is
derived from these four tables with queries, not stored.

Usage
-----
    db = connect("wholesale.db")
    init_schema(db)

    lead_id = insert_lead(db, {...})
    log_message(db, lead_id=lead_id, direction="outbound", ...)
    leads = list_leads(db, stage="active")
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                   TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,

    -- property
    property_address     TEXT NOT NULL,
    zip_code             TEXT,
    parcel_id            TEXT,

    -- owner contact (single owner + optional second, flattened)
    owner_name           TEXT,
    owner_name_2         TEXT,
    owner_phone          TEXT,
    owner_email          TEXT,
    owner_mailing        TEXT,

    -- property details (for scoring, buyer matching, display)
    estimated_arv        REAL,
    estimated_repair     REAL,
    mortgage_balance     REAL,
    free_and_clear       INTEGER,   -- 0/1
    square_feet          INTEGER,
    year_built           INTEGER,
    bedrooms             INTEGER,
    bathrooms            REAL,
    property_type        TEXT,

    -- motivation signals (raw, not aggregated)
    pre_foreclosure      INTEGER,
    tax_delinquent_yrs   INTEGER,
    probate              INTEGER,
    vacant               INTEGER,
    absentee_miles       REAL,
    years_owned          INTEGER,
    code_violations      INTEGER,
    evictions_12mo       INTEGER,
    divorce              INTEGER,
    bankruptcy           INTEGER,
    expired_listing_days INTEGER,

    -- scoring output (cached)
    score                REAL,
    score_confidence     REAL,
    archetype            TEXT,

    -- pipeline
    stage                TEXT NOT NULL DEFAULT 'new',
    stage_changed_at     TEXT,
    seller_asking        REAL,

    -- meta
    source_list          TEXT,       -- PropStream list name or manual entry
    opted_out            INTEGER NOT NULL DEFAULT 0,
    dead_reason          TEXT,
    notes                TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_zip ON leads(zip_code);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score DESC);

CREATE TABLE IF NOT EXISTS buyers (
    id                   TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    name                 TEXT NOT NULL,
    entity_type          TEXT,      -- LLC, Individual, Trust, Fund
    primary_contact      TEXT,
    phone                TEXT,
    email                TEXT,
    preferred_channel    TEXT,      -- email, call, mail

    -- buy-box (flattened)
    zip_codes            TEXT,      -- comma-separated
    property_types       TEXT,      -- comma-separated, default 'SFR'
    min_arv              REAL,
    max_arv              REAL,
    min_beds             INTEGER,
    min_year_built       INTEGER,
    max_repair_pct       REAL,      -- e.g., 0.30
    flood_ok             INTEGER NOT NULL DEFAULT 0,
    hoa_ok               INTEGER NOT NULL DEFAULT 0,

    -- proof of funds
    pof_on_file          INTEGER NOT NULL DEFAULT 0,
    pof_amount           REAL,

    -- stats (updated on offer/close events)
    offers_sent          INTEGER NOT NULL DEFAULT 0,
    deals_closed         INTEGER NOT NULL DEFAULT 0,
    deals_fell_through   INTEGER NOT NULL DEFAULT 0,
    avg_actual_discount  REAL,      -- running mean of purchase_price/arv
    last_closed_at       TEXT,

    notes                TEXT
);

CREATE INDEX IF NOT EXISTS idx_buyers_zips ON buyers(zip_codes);

CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    lead_id       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    direction     TEXT NOT NULL,       -- 'outbound' | 'inbound'
    channel       TEXT NOT NULL,       -- 'mail' | 'email' | 'call' | 'sms'
    subject       TEXT,
    body          TEXT,
    template_id   TEXT,                -- null if free-form
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id, created_at);

CREATE TABLE IF NOT EXISTS offers (
    id              TEXT PRIMARY KEY,
    lead_id         TEXT NOT NULL,
    buyer_id        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL,     -- 'sent' | 'interested' | 'passed' | 'matched' | 'closed' | 'fell_through'
    offered_price   REAL,
    notes           TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (buyer_id) REFERENCES buyers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_offers_lead ON offers(lead_id);
CREATE INDEX IF NOT EXISTS idx_offers_buyer ON offers(buyer_id);
"""

LEAD_STAGES = (
    "new", "attempted", "contacted", "conversation",
    "offer_out", "under_contract", "assigned", "dead",
)


def init_schema(db: sqlite3.Connection):
    db.executescript(SCHEMA)
    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def insert_lead(db: sqlite3.Connection, data: dict) -> str:
    """
    Insert a lead.  `data` is a flat dict matching the columns above
    (minus id/created_at/updated_at which we generate).  Extra keys
    are silently ignored — helpful for importer flexibility.
    """
    now = _now()
    lead_id = _id("lead")
    cols = _lead_columns()
    row = {k: data.get(k) for k in cols if k not in ("id", "created_at", "updated_at")}
    row["id"] = lead_id
    row["created_at"] = now
    row["updated_at"] = now
    row["stage_changed_at"] = now
    if not row.get("stage"):
        row["stage"] = "new"
    if row.get("opted_out") is None:
        row["opted_out"] = 0

    placeholders = ", ".join(":" + c for c in cols)
    db.execute(f"INSERT INTO leads ({', '.join(cols)}) VALUES ({placeholders})", row)
    db.commit()
    return lead_id


def get_lead(db: sqlite3.Connection, lead_id: str) -> Optional[dict]:
    r = db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _dict(r)


def list_leads(db: sqlite3.Connection, *,
               stage: Optional[str] = None,
               min_score: Optional[float] = None,
               zip_code: Optional[str] = None,
               limit: int = 200) -> list[dict]:
    q = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if stage:
        q += " AND stage = ?"
        params.append(stage)
    if min_score is not None:
        q += " AND score >= ?"
        params.append(min_score)
    if zip_code:
        q += " AND zip_code = ?"
        params.append(zip_code)
    q += " ORDER BY score DESC NULLS LAST LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.execute(q, params).fetchall()]


def update_lead(db: sqlite3.Connection, lead_id: str, updates: dict):
    if not updates:
        return
    cols = _lead_columns()
    fields = {k: v for k, v in updates.items() if k in cols and k != "id"}
    fields["updated_at"] = _now()
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = lead_id
    db.execute(f"UPDATE leads SET {set_clause} WHERE id = :id", fields)
    db.commit()


def set_stage(db: sqlite3.Connection, lead_id: str, stage: str):
    assert stage in LEAD_STAGES, f"bad stage {stage!r}"
    db.execute(
        "UPDATE leads SET stage = ?, stage_changed_at = ?, updated_at = ? WHERE id = ?",
        (stage, _now(), _now(), lead_id),
    )
    db.commit()


def mark_opted_out(db: sqlite3.Connection, lead_id: str):
    db.execute(
        "UPDATE leads SET opted_out = 1, stage = 'dead', dead_reason = 'opted_out',"
        " stage_changed_at = ?, updated_at = ? WHERE id = ?",
        (_now(), _now(), lead_id),
    )
    db.commit()


def queue_counts(db: sqlite3.Connection) -> dict:
    """Counts by stage for the queue view."""
    rows = db.execute(
        "SELECT stage, COUNT(*) AS n FROM leads GROUP BY stage"
    ).fetchall()
    return {r["stage"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def log_message(db: sqlite3.Connection, *, lead_id: str, direction: str,
                channel: str, body: str, subject: Optional[str] = None,
                template_id: Optional[str] = None) -> str:
    assert direction in ("outbound", "inbound")
    assert channel in ("mail", "email", "call", "sms")
    msg_id = _id("msg")
    db.execute(
        "INSERT INTO messages (id, lead_id, created_at, direction, channel,"
        " subject, body, template_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, lead_id, _now(), direction, channel, subject, body, template_id),
    )
    # Advance lead stage minimally
    lead = get_lead(db, lead_id)
    if lead:
        cur_stage = lead["stage"]
        new_stage = cur_stage
        if direction == "outbound" and cur_stage == "new":
            new_stage = "attempted"
        elif direction == "inbound" and cur_stage in ("new", "attempted"):
            new_stage = "contacted"
        if new_stage != cur_stage:
            set_stage(db, lead_id, new_stage)

        # Auto opt-out detection for inbound
        if direction == "inbound" and _looks_like_opt_out(body):
            mark_opted_out(db, lead_id)

    db.commit()
    return msg_id


def get_messages(db: sqlite3.Connection, lead_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM messages WHERE lead_id = ? ORDER BY created_at",
        (lead_id,),
    ).fetchall()
    return [dict(r) for r in rows]


_OPT_OUT_PHRASES = ("stop", "unsubscribe", "remove me", "do not contact",
                    "take me off", "lose my number", "opt out", "optout")


def _looks_like_opt_out(body: str) -> bool:
    if not body:
        return False
    low = body.strip().lower()
    if low in ("stop", "unsubscribe", "cancel", "end", "quit", "remove"):
        return True
    return any(p in low for p in _OPT_OUT_PHRASES)


# ---------------------------------------------------------------------------
# Buyers
# ---------------------------------------------------------------------------

def insert_buyer(db: sqlite3.Connection, data: dict) -> str:
    now = _now()
    buyer_id = _id("buyer")
    cols = _buyer_columns()
    row = {k: data.get(k) for k in cols if k not in ("id", "created_at", "updated_at")}
    row["id"] = buyer_id
    row["created_at"] = now
    row["updated_at"] = now
    if not row.get("property_types"):
        row["property_types"] = "SFR"
    for k in ("flood_ok", "hoa_ok", "pof_on_file",
              "offers_sent", "deals_closed", "deals_fell_through"):
        if row.get(k) is None:
            row[k] = 0
    placeholders = ", ".join(":" + c for c in cols)
    db.execute(
        f"INSERT INTO buyers ({', '.join(cols)}) VALUES ({placeholders})", row
    )
    db.commit()
    return buyer_id


def get_buyer(db: sqlite3.Connection, buyer_id: str) -> Optional[dict]:
    r = db.execute("SELECT * FROM buyers WHERE id = ?", (buyer_id,)).fetchone()
    return _dict(r)


def list_buyers(db: sqlite3.Connection, *,
                zip_code: Optional[str] = None) -> list[dict]:
    if zip_code:
        # Cheap substring match on the comma-separated list
        rows = db.execute(
            "SELECT * FROM buyers WHERE zip_codes LIKE ?",
            (f"%{zip_code}%",),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM buyers ORDER BY deals_closed DESC, name"
        ).fetchall()
    return [dict(r) for r in rows]


def record_offer_sent(db: sqlite3.Connection, buyer_id: str):
    db.execute(
        "UPDATE buyers SET offers_sent = offers_sent + 1, updated_at = ? WHERE id = ?",
        (_now(), buyer_id),
    )
    db.commit()


def record_deal_closed(db: sqlite3.Connection, buyer_id: str, *,
                       arv: float, purchase_price: float):
    b = get_buyer(db, buyer_id)
    if not b:
        raise ValueError(f"no buyer {buyer_id}")
    new_discount = purchase_price / arv
    new_count = b["deals_closed"] + 1
    prior = b["avg_actual_discount"]
    if prior is None:
        new_avg = new_discount
    else:
        new_avg = (prior * b["deals_closed"] + new_discount) / new_count
    db.execute(
        "UPDATE buyers SET deals_closed = ?, avg_actual_discount = ?,"
        " last_closed_at = ?, updated_at = ? WHERE id = ?",
        (new_count, new_avg, _now(), _now(), buyer_id),
    )
    db.commit()


def record_fell_through(db: sqlite3.Connection, buyer_id: str):
    db.execute(
        "UPDATE buyers SET deals_fell_through = deals_fell_through + 1,"
        " updated_at = ? WHERE id = ?",
        (_now(), buyer_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Offers (lead → buyer pairings)
# ---------------------------------------------------------------------------

def create_offer(db: sqlite3.Connection, *, lead_id: str, buyer_id: str,
                 offered_price: Optional[float] = None,
                 status: str = "sent") -> str:
    offer_id = _id("ofr")
    db.execute(
        "INSERT INTO offers (id, lead_id, buyer_id, created_at, status, offered_price)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (offer_id, lead_id, buyer_id, _now(), status, offered_price),
    )
    record_offer_sent(db, buyer_id)
    db.commit()
    return offer_id


def get_offers_for_lead(db: sqlite3.Connection, lead_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT o.*, b.name AS buyer_name FROM offers o"
        " JOIN buyers b ON o.buyer_id = b.id"
        " WHERE o.lead_id = ? ORDER BY o.created_at",
        (lead_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Column introspection
# ---------------------------------------------------------------------------

def _lead_columns() -> list[str]:
    return [
        "id", "created_at", "updated_at",
        "property_address", "zip_code", "parcel_id",
        "owner_name", "owner_name_2", "owner_phone", "owner_email", "owner_mailing",
        "estimated_arv", "estimated_repair", "mortgage_balance", "free_and_clear",
        "square_feet", "year_built", "bedrooms", "bathrooms", "property_type",
        "pre_foreclosure", "tax_delinquent_yrs", "probate", "vacant",
        "absentee_miles", "years_owned", "code_violations", "evictions_12mo",
        "divorce", "bankruptcy", "expired_listing_days",
        "score", "score_confidence", "archetype",
        "stage", "stage_changed_at", "seller_asking",
        "source_list", "opted_out", "dead_reason", "notes",
    ]


def _buyer_columns() -> list[str]:
    return [
        "id", "created_at", "updated_at",
        "name", "entity_type", "primary_contact", "phone", "email",
        "preferred_channel",
        "zip_codes", "property_types", "min_arv", "max_arv",
        "min_beds", "min_year_built", "max_repair_pct",
        "flood_ok", "hoa_ok",
        "pof_on_file", "pof_amount",
        "offers_sent", "deals_closed", "deals_fell_through",
        "avg_actual_discount", "last_closed_at",
        "notes",
    ]


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "wholesale_smoke.db")
    if os.path.exists(path):
        os.remove(path)
    db = connect(path)
    init_schema(db)

    lead_id = insert_lead(db, {
        "property_address": "1234 Elm St, Memphis, TN 38127",
        "zip_code": "38127",
        "owner_name": "Jane Doe",
        "owner_phone": "+19015551234",
        "owner_email": "jane@email.com",
        "owner_mailing": "5678 Oak Rd, Atlanta, GA 30301",
        "estimated_arv": 135000,
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
        "score": 87,
        "score_confidence": 95,
        "archetype": "probate",
        "source_list": "PropStream 38127 probate",
    })

    buyer_id = insert_buyer(db, {
        "name": "Mid-South Rental Fund LLC",
        "entity_type": "LLC",
        "primary_contact": "Jacob Patel",
        "email": "jacob@midsouthrental.com",
        "preferred_channel": "email",
        "zip_codes": "38127,38109,38118,38115",
        "property_types": "SFR",
        "min_arv": 55000, "max_arv": 140000,
        "max_repair_pct": 0.30,
        "min_beds": 2, "min_year_built": 1950,
        "pof_on_file": 1, "pof_amount": 400000,
    })

    log_message(db, lead_id=lead_id, direction="outbound",
                channel="mail", body="Probate postcard v1",
                template_id="mail_probate_v2")
    log_message(db, lead_id=lead_id, direction="inbound",
                channel="email",
                body="Maybe. What are you thinking price-wise?")

    print("Lead after inbound reply:")
    lead = get_lead(db, lead_id)
    print(f"  stage:       {lead['stage']}")
    print(f"  opted_out:   {lead['opted_out']}")
    print(f"  score:       {lead['score']}%")

    print("\nMessages:")
    for m in get_messages(db, lead_id):
        arrow = "→" if m["direction"] == "outbound" else "←"
        print(f"  {m['created_at'][:19]}  {arrow} {m['channel']:<5}  "
              f"{(m['body'] or '')[:50]}")

    create_offer(db, lead_id=lead_id, buyer_id=buyer_id, offered_price=72000)
    print("\nOffers for lead:")
    for o in get_offers_for_lead(db, lead_id):
        print(f"  {o['status']:<10}  ${o['offered_price']:,.0f}  {o['buyer_name']}")

    print("\nQueue counts:", queue_counts(db))

    # Opt-out test
    log_message(db, lead_id=lead_id, direction="inbound",
                channel="email", body="please stop contacting me")
    lead = get_lead(db, lead_id)
    print(f"\nAfter 'please stop' reply — stage: {lead['stage']}, "
          f"opted_out: {lead['opted_out']}")
