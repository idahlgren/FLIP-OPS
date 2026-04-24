"""
app.py
======

Flask web app shell.  Wraps the modules (db, scoring, buyer_matching,
templates, propstream_import, email_sender, auth) in a browsable UI.

Routes
------
  GET  /                  queue / home
  GET  /leads/<id>        lead detail
  POST /leads/<id>/stage  advance stage
  POST /leads/<id>/msg    log + optionally send message
  GET  /buyers            buyer list
  POST /buyers            add a buyer
  POST /import            upload PropStream CSV
"""

from __future__ import annotations

import os
import tempfile
from flask import (Flask, request, redirect, url_for,
                   render_template_string, flash, abort)

import db as db_module
from propstream_import import import_file
from buyer_matching import match, count_matches
from templates import compose
from scoring import score_lead
from auth import require_auth_globally
from email_sender import send_email, is_configured as email_configured
from ai import (score_lead_ai, analyze_lead, suggest_actions,
                personalize_draft, detect_archetype_ai)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-prod")
app.before_request(require_auth_globally)

DB_PATH = os.environ.get("DB_PATH", "wholesale.db")
SENDER_NAME = os.environ.get("SENDER_NAME", "Alex Chen")
SENDER_PHONE = os.environ.get("SENDER_PHONE", "(901) 555-0199")
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Midsouth Home Partners LLC")
BUSINESS_ADDRESS = os.environ.get("BUSINESS_ADDRESS",
                                   "123 Main St, Memphis, TN 38103")


def get_db():
    conn = db_module.connect(DB_PATH)
    db_module.init_schema(conn)
    return conn


def _tier_letter(score: float) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "skip"


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

QUEUE_TPL = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Queue — Wholesale tool</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.55;
    color: #c7ccd5;
    background: #16191f;
    max-width: 960px;
    margin: 0 auto;
    padding: 2.25rem 1.5rem 4rem;
    letter-spacing: -0.003em;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  a { color: #4da3ff; text-decoration: none; }
  a:hover { color: #66b0ff; text-decoration: underline; }

  h1, h2, h3 { font-weight: 500; margin: 0; color: #e8eaed; }
  h1 { font-size: 24px; letter-spacing: -0.015em; }
  h2 {
    font-size: 11px;
    color: #8892a0;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 500;
    margin-bottom: 0.85rem;
  }

  .site-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
    padding-bottom: 1.15rem;
    border-bottom: 1px solid #262d38;
  }
  .site-logo img { height: 54px; display: block; }
  nav {
    display: flex;
    gap: 1.75rem;
    font-size: 14px;
  }
  nav a { color: #8892a0; text-decoration: none; }
  nav a:hover { color: #c7ccd5; text-decoration: none; }
  nav a.current { color: #e8eaed; font-weight: 500; }

  .header-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 1.75rem;
  }
  .header-row .meta {
    font-size: 13px;
    color: #5f6977;
    font-variant-numeric: tabular-nums;
  }

  .summary {
    display: flex;
    gap: 0.6rem;
    margin-bottom: 2rem;
    flex-wrap: wrap;
  }
  .summary .card {
    padding: 0.85rem 1.1rem;
    background: #1e242d;
    border: 1px solid #262d38;
    border-radius: 8px;
    flex: 1 1 115px;
    min-width: 115px;
  }
  .summary .label {
    font-size: 10px;
    color: #8892a0;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
  }
  .summary .val {
    font-size: 24px;
    font-weight: 500;
    margin-top: 4px;
    color: #e8eaed;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  .table-wrap {
    border: 1px solid #262d38;
    border-radius: 8px;
    overflow: hidden;
    background: #1a1f27;
  }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left;
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8892a0;
    padding: 0.75rem 1rem;
    background: #1e242d;
    border-bottom: 1px solid #262d38;
  }
  tbody td {
    padding: 0.95rem 1rem;
    border-bottom: 1px solid #22282f;
    font-size: 14px;
    vertical-align: baseline;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: #20262f; }

  .score {
    display: inline-block;
    min-width: 38px;
    padding: 3px 8px;
    border-radius: 5px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    font-size: 13px;
    text-align: center;
  }
  .score.a {
    background: rgba(74, 222, 128, 0.12);
    color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.2);
  }
  .score.b {
    background: rgba(163, 230, 53, 0.1);
    color: #a3e635;
    border: 1px solid rgba(163, 230, 53, 0.18);
  }
  .score.c {
    background: rgba(250, 204, 21, 0.1);
    color: #facc15;
    border: 1px solid rgba(250, 204, 21, 0.2);
  }
  .score.d {
    background: rgba(251, 146, 60, 0.1);
    color: #fb923c;
    border: 1px solid rgba(251, 146, 60, 0.2);
  }

  .property-link { color: #c7ccd5; font-weight: 400; }
  .property-link:hover { color: #e8eaed; text-decoration: none; }
  .owner { color: #8892a0; font-size: 13px; }

  .pill {
    display: inline-block;
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 999px;
    background: rgba(140, 146, 160, 0.12);
    color: #8892a0;
    font-weight: 500;
    letter-spacing: 0.01em;
  }
  .pill.new {
    background: rgba(77, 163, 255, 0.12);
    color: #4da3ff;
  }
  .pill.contacted {
    background: rgba(74, 222, 128, 0.12);
    color: #4ade80;
  }
  .pill.attempted {
    background: rgba(250, 204, 21, 0.12);
    color: #facc15;
  }

  .archetype {
    font-size: 12px;
    color: #8892a0;
    font-variant: small-caps;
    letter-spacing: 0.03em;
  }

  .section-divider {
    margin-top: 3rem;
    padding-top: 2rem;
    border-top: 1px solid #262d38;
  }

  form.import-form {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    padding: 1.5rem;
    background: #1e242d;
    border: 1px solid #262d38;
    border-radius: 8px;
  }

  input[type=file] {
    font-size: 13px;
    color: #c7ccd5;
  }
  input[type=file]::-webkit-file-upload-button {
    background: #262d38;
    color: #e8eaed;
    border: 1px solid #3a4252;
    border-radius: 5px;
    padding: 6px 12px;
    margin-right: 10px;
    font-family: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  input[type=file]::-webkit-file-upload-button:hover {
    background: #2d3540;
  }

  button {
    font-family: inherit;
    font-size: 13px;
    padding: 0.55rem 1rem;
    border: 1px solid #3a4252;
    background: #262d38;
    color: #e8eaed;
    border-radius: 6px;
    cursor: pointer;
    line-height: 1.2;
    transition: background 0.15s;
  }
  button:hover { background: #2d3540; }
  button.primary {
    background: #4da3ff;
    border-color: #4da3ff;
    color: #0a0d12;
    font-weight: 500;
  }
  button.primary:hover { background: #66b0ff; border-color: #66b0ff; }

  .hint { font-size: 12px; color: #5f6977; }

  .flash {
    background: rgba(77, 163, 255, 0.08);
    border: 1px solid rgba(77, 163, 255, 0.2);
    color: #c7ccd5;
    padding: 0.7rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.25rem;
    font-size: 13px;
  }

  @media (max-width: 640px) {
    body { padding: 1.5rem 1rem 3rem; }
    .summary .card { flex-basis: calc(50% - 0.3rem); }
    thead { display: none; }
    tbody tr { display: block; padding: 0.9rem 1rem; border-bottom: 1px solid #22282f; }
    tbody td { display: inline-block; border: none; padding: 2px 8px 2px 0; }
    tbody td:first-child { display: block; margin-bottom: 4px; }
  }
</style>
</head>
<body>

<div class="site-header">
  <a class="site-logo" href="{{ url_for('queue') }}"><img src="{{ url_for('static', filename='logo.png') }}" alt="Dogman's Flip Ops" /></a>
  <nav>
    <a href="{{ url_for('queue') }}" class="current">Queue</a>
    <a href="{{ url_for('buyers_page') }}">Buyers</a>
  </nav>
</div>

{% with messages = get_flashed_messages() %}
  {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
{% endwith %}

<div class="header-row">
  <h1>Queue</h1>
  <div class="meta">{{ leads | length }} active</div>
</div>

<div class="summary">
  {% for stage, count in counts.items() %}
    <div class="card">
      <div class="label">{{ stage }}</div>
      <div class="val">{{ count }}</div>
    </div>
  {% endfor %}
  {% if not counts %}
    <div class="card">
      <div class="label">No leads yet</div>
      <div class="val">0</div>
    </div>
  {% endif %}
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th style="width: 70px;">Score</th>
        <th>Property</th>
        <th style="width: 180px;">Owner</th>
        <th style="width: 110px;">Stage</th>
        <th style="width: 130px;">Archetype</th>
      </tr>
    </thead>
    <tbody>
      {% for lead in leads %}
        <tr>
          <td><span class="score {{ lead.tier.lower() }}">{{ lead.score | round(0) | int }}</span></td>
          <td><a class="property-link" href="{{ url_for('lead_detail', lead_id=lead.id) }}">{{ lead.property_address }}</a></td>
          <td class="owner">{{ lead.owner_name or '—' }}</td>
          <td><span class="pill {{ lead.stage }}">{{ lead.stage }}</span></td>
          <td class="archetype">{{ lead.archetype or '—' }}</td>
        </tr>
      {% endfor %}
      {% if not leads %}
        <tr><td colspan="5" style="color: #5f6977; padding: 2.5rem; text-align: center;">
          No leads yet. Import a PropStream CSV below.
        </td></tr>
      {% endif %}
    </tbody>
  </table>
</div>

<div class="section-divider" id="import-section">
  <h2>Import PropStream CSV</h2>
  <form class="import-form" action="{{ url_for('import_csv') }}" method="post" enctype="multipart/form-data">
    <input type="file" name="csv" accept=".csv" required />
    <button class="primary" type="submit">Import</button>
    <span class="hint">Leads below 70% are auto-rejected. Buyer matches enrich the score on import.</span>
  </form>
</div>

</body>
</html>
"""


@app.route("/")
def queue():
    conn = get_db()
    rows = db_module.list_leads(conn, limit=200)
    for r in rows:
        r["tier"] = _tier_letter(r.get("score") or 0)
    counts = db_module.queue_counts(conn)
    return render_template_string(QUEUE_TPL, leads=rows, counts=counts)


# ---------------------------------------------------------------------------
# Lead detail
# ---------------------------------------------------------------------------

LEAD_TPL = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{{ lead.property_address }} — Wholesale tool</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.55;
    color: #c7ccd5;
    background: #16191f;
    max-width: 960px;
    margin: 0 auto;
    padding: 2.25rem 1.5rem 4rem;
    letter-spacing: -0.003em;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  a { color: #4da3ff; text-decoration: none; }
  a:hover { color: #66b0ff; text-decoration: underline; }

  h1, h2, h3 { font-weight: 500; margin: 0; color: #e8eaed; }
  h1 { font-size: 22px; letter-spacing: -0.015em; }
  h2 {
    font-size: 11px;
    color: #8892a0;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 500;
    margin-bottom: 0.95rem;
  }

  .site-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
    padding-bottom: 1.15rem;
    border-bottom: 1px solid #262d38;
  }
  .site-logo img { height: 54px; display: block; }
  nav {
    display: flex;
    gap: 1.75rem;
    font-size: 14px;
  }
  nav a { color: #8892a0; text-decoration: none; }
  nav a:hover { color: #c7ccd5; text-decoration: none; }

  .back {
    color: #5f6977;
    font-size: 13px;
    display: inline-block;
    margin-bottom: 1.5rem;
    text-decoration: none;
  }
  .back:hover { color: #c7ccd5; text-decoration: none; }

  .header { margin-bottom: 1.5rem; }
  .header-meta {
    color: #8892a0;
    font-size: 13px;
    margin-top: 7px;
    display: flex;
    align-items: center;
    gap: 0.65rem;
    flex-wrap: wrap;
  }
  .header-meta .dot { color: #404855; }

  .score-header {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 5px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .score-header.a {
    background: rgba(74, 222, 128, 0.12);
    color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.2);
  }
  .score-header.b {
    background: rgba(163, 230, 53, 0.1);
    color: #a3e635;
    border: 1px solid rgba(163, 230, 53, 0.18);
  }
  .score-header.c {
    background: rgba(250, 204, 21, 0.1);
    color: #facc15;
    border: 1px solid rgba(250, 204, 21, 0.2);
  }
  .score-header.d {
    background: rgba(251, 146, 60, 0.1);
    color: #fb923c;
    border: 1px solid rgba(251, 146, 60, 0.2);
  }

  .pill {
    display: inline-block;
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 999px;
    background: rgba(140, 146, 160, 0.12);
    color: #8892a0;
    font-weight: 500;
    letter-spacing: 0.01em;
  }
  .pill.new { background: rgba(77, 163, 255, 0.12); color: #4da3ff; }
  .pill.contacted { background: rgba(74, 222, 128, 0.12); color: #4ade80; }
  .pill.attempted { background: rgba(250, 204, 21, 0.12); color: #facc15; }

  .opted-out {
    color: #f87171;
    font-weight: 500;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .panel {
    border: 1px solid #262d38;
    border-radius: 8px;
    padding: 1.35rem 1.5rem;
    margin-bottom: 1.25rem;
    background: #1a1f27;
  }

  .flash {
    background: rgba(77, 163, 255, 0.08);
    border: 1px solid rgba(77, 163, 255, 0.2);
    color: #c7ccd5;
    padding: 0.7rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.25rem;
    font-size: 13px;
  }

  /* Score factors */
  .factor {
    display: flex;
    align-items: center;
    font-size: 13px;
    margin: 11px 0;
  }
  .factor .name {
    width: 110px;
    color: #8892a0;
  }
  .factor .bar {
    flex: 1;
    height: 6px;
    background: #262d38;
    border-radius: 3px;
    overflow: hidden;
    margin: 0 14px;
  }
  .factor .fill {
    height: 100%;
    background: #4ade80;
    border-radius: 3px;
    transition: width 0.3s;
  }
  .factor .pct {
    width: 42px;
    text-align: right;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    color: #e8eaed;
  }
  .factor .weight {
    width: 52px;
    text-align: right;
    color: #5f6977;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  /* Details KV table */
  table.kv { width: 100%; font-size: 13px; }
  table.kv td {
    padding: 5px 0;
    vertical-align: top;
  }
  table.kv td:first-child {
    color: #8892a0;
    width: 150px;
    padding-right: 1rem;
  }
  table.kv td:last-child { color: #c7ccd5; }
  .free-clear {
    display: inline-block;
    background: rgba(74, 222, 128, 0.12);
    color: #4ade80;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 999px;
    margin-left: 8px;
    font-weight: 500;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  /* Buyer matches */
  .buyer-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 12px 0;
    border-bottom: 1px solid #22282f;
    font-size: 13px;
    gap: 1rem;
  }
  .buyer-row:last-child { border-bottom: none; padding-bottom: 0; }
  .buyer-row b { color: #e8eaed; font-weight: 500; }
  .buyer-row .meta-row {
    font-size: 11px;
    color: #5f6977;
    margin-top: 3px;
  }
  .buyer-row .stats {
    color: #8892a0;
    font-size: 12px;
    white-space: nowrap;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .rank {
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    color: #4da3ff;
  }

  /* Conversation */
  .msg {
    padding: 11px 15px;
    border-radius: 8px;
    margin: 10px 0;
    font-size: 13px;
    line-height: 1.55;
    border: 1px solid #262d38;
  }
  .msg.outbound { background: #1e242d; }
  .msg.inbound {
    background: #1a2330;
    border-color: rgba(77, 163, 255, 0.2);
    margin-left: 2rem;
  }
  .msg .meta-row {
    font-size: 11px;
    color: #5f6977;
    margin-bottom: 5px;
    font-variant-numeric: tabular-nums;
  }
  .msg .subject {
    font-weight: 500;
    margin-bottom: 4px;
    color: #e8eaed;
  }
  .msg .body {
    white-space: pre-wrap;
    color: #c7ccd5;
  }

  /* Compose */
  label {
    font-size: 11px;
    color: #8892a0;
    display: block;
    margin-bottom: 5px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }
  input[type=text], input[type=number], select, textarea {
    font-family: inherit;
    font-size: 14px;
    padding: 9px 11px;
    border: 1px solid #2d3540;
    background: #16191f;
    color: #e8eaed;
    border-radius: 6px;
    width: 100%;
    line-height: 1.4;
    transition: border-color 0.15s;
  }
  input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: #4da3ff;
    box-shadow: 0 0 0 3px rgba(77, 163, 255, 0.1);
  }
  textarea {
    min-height: 180px;
    font-size: 13px;
    line-height: 1.65;
    font-family: ui-monospace, "SF Mono", Consolas, monospace;
  }

  .template-note {
    font-size: 12px;
    color: #8892a0;
    margin-bottom: 12px;
    padding: 8px 12px;
    background: rgba(77, 163, 255, 0.06);
    border: 1px solid rgba(77, 163, 255, 0.15);
    border-radius: 6px;
  }
  .template-note b { color: #e8eaed; font-weight: 500; }

  .form-actions {
    margin-top: 14px;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .form-actions select { width: auto; }
  .form-actions .send-check {
    font-size: 13px;
    color: #c7ccd5;
    display: flex;
    align-items: center;
    gap: 6px;
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
    margin: 0;
  }
  .form-actions input[type=checkbox] {
    accent-color: #4da3ff;
    width: 14px;
    height: 14px;
  }

  button {
    font-family: inherit;
    font-size: 13px;
    padding: 0.6rem 1.1rem;
    border: 1px solid #3a4252;
    background: #262d38;
    color: #e8eaed;
    border-radius: 6px;
    cursor: pointer;
    line-height: 1.2;
    transition: all 0.15s;
  }
  button:hover { background: #2d3540; border-color: #404855; }
  button.primary {
    background: #4da3ff;
    border-color: #4da3ff;
    color: #0a0d12;
    font-weight: 500;
  }
  button.primary:hover {
    background: #66b0ff;
    border-color: #66b0ff;
  }

  .warn-banner {
    background: rgba(248, 113, 113, 0.08);
    border: 1px solid rgba(248, 113, 113, 0.25);
    color: #f87171;
    padding: 0.7rem 0.95rem;
    border-radius: 6px;
    font-size: 13px;
  }

  .stage-form { display: flex; gap: 10px; align-items: center; }
  .stage-form select { width: 220px; }

  .empty { color: #5f6977; padding: 1rem 0; font-size: 13px; }

  /* AI sections */
  .ai-badge {
    display: inline-block;
    font-size: 9px;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(77, 163, 255, 0.12);
    color: #4da3ff;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-left: 8px;
    vertical-align: middle;
  }
  .ai-panel {
    border-color: rgba(77, 163, 255, 0.25);
    background: #1a1f27;
  }
  .ai-analysis {
    font-size: 13px;
    line-height: 1.65;
    color: #c7ccd5;
  }
  .ai-reasoning {
    font-size: 12px;
    color: #8892a0;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid #22282f;
    line-height: 1.55;
  }
  .ai-flags {
    margin-top: 8px;
    font-size: 12px;
  }
  .ai-flags span {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(250, 204, 21, 0.1);
    color: #facc15;
    border: 1px solid rgba(250, 204, 21, 0.2);
    margin: 2px 4px 2px 0;
  }
  .ai-score-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-top: 1px solid #22282f;
    margin-top: 12px;
    font-size: 13px;
  }
  .ai-score-val {
    font-size: 18px;
    font-weight: 500;
    color: #4da3ff;
    font-variant-numeric: tabular-nums;
  }
  .ai-actions-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .ai-actions-list li {
    padding: 8px 0;
    border-bottom: 1px solid #22282f;
    font-size: 13px;
    color: #c7ccd5;
  }
  .ai-actions-list li:last-child { border-bottom: none; }
  .ai-actions-list li::before {
    content: "→";
    color: #4da3ff;
    margin-right: 8px;
    font-weight: 500;
  }
  .ai-draft-toggle {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #22282f;
  }
  .ai-draft-toggle summary {
    font-size: 12px;
    color: #4da3ff;
    cursor: pointer;
    font-weight: 500;
  }
  .ai-draft-preview {
    margin-top: 10px;
    padding: 12px;
    background: #16191f;
    border: 1px solid #2d3540;
    border-radius: 6px;
    font-size: 13px;
    white-space: pre-wrap;
    color: #c7ccd5;
    line-height: 1.6;
  }

  @media (max-width: 640px) {
    body { padding: 1.5rem 1rem 3rem; }
    .buyer-row { flex-direction: column; gap: 0.5rem; }
    .buyer-row .stats { text-align: left; }
    table.kv td:first-child { width: 120px; }
    .msg.inbound { margin-left: 0; }
    .factor .weight { display: none; }
  }
</style>
</head>
<body>

<div class="site-header">
  <a class="site-logo" href="{{ url_for('queue') }}"><img src="{{ url_for('static', filename='logo.png') }}" alt="Dogman's Flip Ops" /></a>
  <nav>
    <a href="{{ url_for('queue') }}">Queue</a>
    <a href="{{ url_for('buyers_page') }}">Buyers</a>
  </nav>
</div>

<a class="back" href="{{ url_for('queue') }}">← queue</a>

<div class="header">
  <h1>{{ lead.property_address }}</h1>
  <div class="header-meta">
    Score <span class="score-header {{ lead.tier.lower() }}">{{ lead.score | round(0) | int }}%</span>
    {% if lead.archetype %}<span class="dot">·</span> {{ lead.archetype }}{% endif %}
    <span class="dot">·</span> stage <span class="pill {{ lead.stage }}">{{ lead.stage }}</span>
    {% if lead.opted_out %}<span class="dot">·</span> <span class="opted-out">OPTED OUT</span>{% endif %}
  </div>
</div>

{% with messages = get_flashed_messages() %}
  {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
{% endwith %}

<div class="panel">
  <h2>Score breakdown</h2>
  {% for name, f in factors.items() %}
    <div class="factor">
      <div class="name">{{ name }}</div>
      <div class="bar"><div class="fill" style="width: {{ f.score }}%"></div></div>
      <div class="pct">{{ f.score | round(0) | int }}</div>
      <div class="weight">{{ (f.weight * 100) | round(0) | int }}%</div>
    </div>
  {% endfor %}
  {% if ai_score %}
    <div class="ai-score-row">
      <div>
        <span style="color: #8892a0;">AI-adjusted score</span>
        <span class="ai-badge">Claude</span>
      </div>
      <div class="ai-score-val">{{ ai_score.adjusted_total | round(0) | int }}%</div>
    </div>
    {% if ai_score.reasoning %}
      <div class="ai-reasoning">{{ ai_score.reasoning }}</div>
    {% endif %}
    {% if ai_score.flags %}
      <div class="ai-flags">
        {% for flag in ai_score.flags %}<span>{{ flag }}</span>{% endfor %}
      </div>
    {% endif %}
  {% endif %}
</div>

<div class="panel">
  <h2>Details</h2>
  <table class="kv">
    <tr><td>Owner</td><td>{{ lead.owner_name or '—' }}{% if lead.owner_name_2 %} + {{ lead.owner_name_2 }}{% endif %}</td></tr>
    <tr><td>Phone</td><td>{{ lead.owner_phone or '—' }}</td></tr>
    <tr><td>Email</td><td>{{ lead.owner_email or '—' }}</td></tr>
    <tr><td>Mailing</td><td>{{ lead.owner_mailing or '—' }}</td></tr>
    <tr><td>ARV / repair</td><td>${{ '{:,.0f}'.format(lead.estimated_arv or 0) }} / ${{ '{:,.0f}'.format(lead.estimated_repair or 0) }}</td></tr>
    <tr><td>Mortgage</td><td>${{ '{:,.0f}'.format(lead.mortgage_balance or 0) }}{% if lead.free_and_clear %} <span class="free-clear">free &amp; clear</span>{% endif %}</td></tr>
    <tr><td>Beds / baths</td><td>{{ lead.bedrooms or '?' }} / {{ lead.bathrooms or '?' }}</td></tr>
    <tr><td>Sqft / year</td><td>{{ lead.square_feet or '?' }} / {{ lead.year_built or '?' }}</td></tr>
    <tr><td>Years owned</td><td>{{ lead.years_owned or '?' }}</td></tr>
    <tr><td>Source list</td><td>{{ lead.source_list or '—' }}</td></tr>
  </table>
</div>

{% if ai_analysis or ai_actions %}
<div class="panel ai-panel">
  <h2>AI Analysis <span class="ai-badge">Claude</span></h2>
  {% if ai_analysis %}
    <div class="ai-analysis">{{ ai_analysis }}</div>
  {% endif %}
  {% if ai_actions %}
    <h2 style="margin-top: 1.25rem;">Next actions</h2>
    <ul class="ai-actions-list">
      {% for action in ai_actions %}
        <li>{{ action }}</li>
      {% endfor %}
    </ul>
  {% endif %}
</div>
{% endif %}

<div class="panel">
  <h2>Top buyer matches</h2>
  {% for b, rank, reasons in buyer_matches[:5] %}
    <div class="buyer-row">
      <div>
        <b>{{ b.name }}</b> — rank <span class="rank">{{ rank | round(0) | int }}</span>
        <div class="meta-row">{{ reasons | join(' · ') }}</div>
      </div>
      <div class="stats">
        {{ b.deals_closed or 0 }} closed{% if b.avg_actual_discount %} · avg {{ (b.avg_actual_discount * 100) | round(0) | int }}% of ARV{% endif %}
      </div>
    </div>
  {% endfor %}
  {% if not buyer_matches %}
    <div class="empty">No buyers match this lead's buy-box yet.</div>
  {% endif %}
</div>

<div class="panel">
  <h2>Conversation</h2>
  {% for m in messages %}
    <div class="msg {{ m.direction }}">
      <div class="meta-row">{{ m.created_at[:16] }} · {{ '→' if m.direction == 'outbound' else '←' }} {{ m.channel }}{% if m.template_id %} · {{ m.template_id }}{% endif %}</div>
      {% if m.subject %}<div class="subject">{{ m.subject }}</div>{% endif %}
      <div class="body">{{ m.body }}</div>
    </div>
  {% endfor %}
  {% if not messages %}
    <div class="empty">No messages yet.</div>
  {% endif %}
</div>

<div class="panel">
  <h2>Compose outreach</h2>
  {% if lead.opted_out %}
    <div class="warn-banner">This lead opted out. Outbound is blocked.</div>
  {% else %}
    <form method="post" action="{{ url_for('lead_log_message', lead_id=lead.id) }}">
      <div class="template-note">
        Template: <b>{{ draft.template_id }}</b>
        {% if draft.subject %} · subject: <b>{{ draft.subject }}</b>{% endif %}
      </div>
      <input type="hidden" name="template_id" value="{{ draft.template_id }}" />
      {% if draft.subject %}
        <label>Subject</label>
        <input type="text" name="subject" value="{{ draft.subject }}" style="margin-bottom: 10px;" />
      {% endif %}
      <label>Body</label>
      <textarea name="body">{{ draft.body }}</textarea>
      <div class="form-actions">
        <select name="channel">
          <option value="email" {% if lead.owner_email %}selected{% endif %}>Email</option>
          <option value="mail">Mail (mark as sent)</option>
          <option value="call">Call (log as contact)</option>
        </select>
        {% if lead.owner_email and email_available %}
          <label class="send-check">
            <input type="checkbox" name="send_email" value="1" checked />
            Send email now
          </label>
        {% elif not email_available %}
          <span style="font-size: 12px; color: #5f6977;">(Gmail SMTP not configured — log only)</span>
        {% endif %}
        <button class="primary" type="submit">Log outbound</button>
      </div>
      {% if ai_draft %}
        <div class="ai-draft-toggle">
          <details>
            <summary>View AI-personalized version <span class="ai-badge">Claude</span></summary>
            {% if ai_draft.subject %}
              <div style="font-size: 12px; color: #8892a0; margin-top: 10px;">Subject: <b style="color: #e8eaed;">{{ ai_draft.subject }}</b></div>
            {% endif %}
            <div class="ai-draft-preview">{{ ai_draft.body }}</div>
            <div style="font-size: 11px; color: #5f6977; margin-top: 6px;">Copy into the editor above to use this version.</div>
          </details>
        </div>
      {% endif %}
    </form>
  {% endif %}
</div>

<div class="panel">
  <h2>Advance stage</h2>
  <form class="stage-form" method="post" action="{{ url_for('lead_set_stage', lead_id=lead.id) }}">
    <select name="stage">
      {% for s in stages %}
        <option value="{{ s }}" {% if s == lead.stage %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
    <button type="submit">Update</button>
  </form>
</div>

</body>
</html>
"""


@app.route("/leads/<lead_id>")
def lead_detail(lead_id):
    conn = get_db()
    lead = db_module.get_lead(conn, lead_id)
    if not lead:
        abort(404)

    lead["tier"] = _tier_letter(lead.get("score") or 0)

    buyers = db_module.list_buyers(conn, zip_code=lead["zip_code"])
    matches = match(lead, buyers)
    messages = db_module.get_messages(conn, lead_id)
    n_buyers = len(matches)
    s = score_lead(lead, matching_buyers=n_buyers)

    draft = compose(
        lead, archetype=lead.get("archetype") or "general",
        channel="email",
        sender_name=SENDER_NAME, sender_phone=SENDER_PHONE,
        business_name=BUSINESS_NAME, business_address=BUSINESS_ADDRESS,
    )

    # AI features
    ai_score = score_lead_ai(lead, s, matching_buyers=n_buyers)
    ai_analysis = analyze_lead(lead, messages, buyer_matches=n_buyers)
    ai_actions = suggest_actions(lead, messages)
    ai_draft = personalize_draft(lead, draft["body"], draft.get("subject"))

    return render_template_string(
        LEAD_TPL, lead=lead, factors=s["factors"], buyer_matches=matches,
        messages=messages, draft=draft,
        stages=db_module.LEAD_STAGES,
        email_available=email_configured(),
        ai_score=ai_score, ai_analysis=ai_analysis,
        ai_actions=ai_actions, ai_draft=ai_draft,
    )


@app.route("/leads/<lead_id>/msg", methods=["POST"])
def lead_log_message(lead_id):
    conn = get_db()
    lead = db_module.get_lead(conn, lead_id)
    if not lead:
        abort(404)
    if lead["opted_out"]:
        flash("lead has opted out — outbound blocked")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    channel = request.form.get("channel", "email")
    body = request.form.get("body", "")
    subject = request.form.get("subject") or None
    template_id = request.form.get("template_id") or None
    send_flag = request.form.get("send_email") == "1"

    # Attempt actual send if requested and configured
    send_note = ""
    if channel == "email" and send_flag and lead.get("owner_email"):
        result = send_email(to=lead["owner_email"], subject=subject or "(no subject)",
                            body=body)
        if result.sent:
            send_note = f" · email sent to {lead['owner_email']}"
        else:
            send_note = f" · SMTP failed: {result.error}"

    db_module.log_message(
        conn, lead_id=lead_id, direction="outbound", channel=channel,
        body=body, subject=subject, template_id=template_id,
    )
    flash(f"logged outbound {channel}{send_note}")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.route("/leads/<lead_id>/stage", methods=["POST"])
def lead_set_stage(lead_id):
    conn = get_db()
    stage = request.form.get("stage")
    if stage not in db_module.LEAD_STAGES:
        abort(400)
    db_module.set_stage(conn, lead_id, stage)
    flash(f"stage → {stage}")
    return redirect(url_for("lead_detail", lead_id=lead_id))


# ---------------------------------------------------------------------------
# Buyers
# ---------------------------------------------------------------------------

BUYERS_TPL = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Buyers — Wholesale tool</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.55;
    color: #c7ccd5;
    background: #16191f;
    max-width: 960px;
    margin: 0 auto;
    padding: 2.25rem 1.5rem 4rem;
    letter-spacing: -0.003em;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  a { color: #4da3ff; text-decoration: none; }
  a:hover { color: #66b0ff; text-decoration: underline; }

  h1, h2, h3 { font-weight: 500; margin: 0; color: #e8eaed; }
  h1 { font-size: 24px; letter-spacing: -0.015em; }
  h2 {
    font-size: 11px;
    color: #8892a0;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 500;
    margin-bottom: 0.95rem;
  }

  .site-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
    padding-bottom: 1.15rem;
    border-bottom: 1px solid #262d38;
  }
  .site-logo img { height: 54px; display: block; }
  nav {
    display: flex;
    gap: 1.75rem;
    font-size: 14px;
  }
  nav a { color: #8892a0; text-decoration: none; }
  nav a:hover { color: #c7ccd5; text-decoration: none; }
  nav a.current { color: #e8eaed; font-weight: 500; }

  .flash {
    background: rgba(77, 163, 255, 0.08);
    border: 1px solid rgba(77, 163, 255, 0.2);
    color: #c7ccd5;
    padding: 0.7rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.25rem;
    font-size: 13px;
  }

  .header-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 1.75rem;
  }
  .header-row .meta {
    font-size: 13px;
    color: #5f6977;
    font-variant-numeric: tabular-nums;
  }

  .table-wrap {
    border: 1px solid #262d38;
    border-radius: 8px;
    overflow: hidden;
    background: #1a1f27;
  }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left;
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8892a0;
    padding: 0.75rem 1rem;
    background: #1e242d;
    border-bottom: 1px solid #262d38;
  }
  tbody td {
    padding: 0.95rem 1rem;
    border-bottom: 1px solid #22282f;
    font-size: 14px;
    vertical-align: baseline;
    color: #c7ccd5;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: #20262f; }
  tbody td b { color: #e8eaed; font-weight: 500; }
  tbody td .sub {
    font-size: 12px;
    color: #5f6977;
    margin-top: 3px;
  }
  .check { color: #4ade80; font-weight: 500; }
  .dash { color: #404855; }
  .tnum { font-variant-numeric: tabular-nums; }

  .panel {
    border: 1px solid #262d38;
    border-radius: 8px;
    padding: 1.35rem 1.5rem;
    margin-top: 2.5rem;
    background: #1a1f27;
  }

  label {
    font-size: 11px;
    color: #8892a0;
    display: block;
    margin-bottom: 5px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }
  input, select {
    font-family: inherit;
    font-size: 14px;
    padding: 8px 11px;
    border: 1px solid #2d3540;
    background: #16191f;
    color: #e8eaed;
    border-radius: 6px;
    width: 100%;
    line-height: 1.3;
    transition: border-color 0.15s;
  }
  input:focus, select:focus {
    outline: none;
    border-color: #4da3ff;
    box-shadow: 0 0 0 3px rgba(77, 163, 255, 0.1);
  }
  input::placeholder { color: #5f6977; }
  .row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-bottom: 14px;
  }

  button {
    font-family: inherit;
    font-size: 13px;
    padding: 0.6rem 1.1rem;
    border: 1px solid #3a4252;
    background: #262d38;
    color: #e8eaed;
    border-radius: 6px;
    cursor: pointer;
    line-height: 1.2;
    transition: all 0.15s;
  }
  button:hover { background: #2d3540; border-color: #404855; }
  button.primary {
    background: #4da3ff;
    border-color: #4da3ff;
    color: #0a0d12;
    font-weight: 500;
  }
  button.primary:hover { background: #66b0ff; border-color: #66b0ff; }

  .hint { font-size: 12px; color: #5f6977; }

  @media (max-width: 640px) {
    body { padding: 1.5rem 1rem 3rem; }
    .row { grid-template-columns: 1fr; }
    thead { display: none; }
    tbody tr { display: block; padding: 0.9rem 1rem; border-bottom: 1px solid #22282f; }
    tbody td { display: block; border: none; padding: 2px 0; }
  }
</style>
</head>
<body>

<div class="site-header">
  <a class="site-logo" href="{{ url_for('queue') }}"><img src="{{ url_for('static', filename='logo.png') }}" alt="Dogman's Flip Ops" /></a>
  <nav>
    <a href="{{ url_for('queue') }}">Queue</a>
    <a href="{{ url_for('buyers_page') }}" class="current">Buyers</a>
  </nav>
</div>

{% with messages = get_flashed_messages() %}
  {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
{% endwith %}

<div class="header-row">
  <h1>Buyers</h1>
  <div class="meta">{{ buyers | length }} total</div>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Name</th>
        <th>Zips</th>
        <th>ARV range</th>
        <th class="tnum" style="width: 70px;">Closed</th>
        <th style="width: 60px;">POF</th>
      </tr>
    </thead>
    <tbody>
      {% for b in buyers %}
        <tr>
          <td>
            <b>{{ b.name }}</b>
            {% if b.primary_contact %}<div class="sub">{{ b.primary_contact }}{% if b.preferred_channel %} · {{ b.preferred_channel }}{% endif %}</div>{% endif %}
          </td>
          <td>{{ b.zip_codes or '—' }}</td>
          <td class="tnum">${{ '{:,.0f}'.format(b.min_arv or 0) }}–${{ '{:,.0f}'.format(b.max_arv or 0) }}</td>
          <td class="tnum">{{ b.deals_closed or 0 }}</td>
          <td>{% if b.pof_on_file %}<span class="check">✓</span>{% else %}<span class="dash">—</span>{% endif %}</td>
        </tr>
      {% endfor %}
      {% if not buyers %}
        <tr><td colspan="5" style="color: #5f6977; padding: 2.5rem; text-align: center;">
          No buyers yet. Add one below.
        </td></tr>
      {% endif %}
    </tbody>
  </table>
</div>

<div class="panel">
  <h2>Add buyer</h2>
  <form method="post" action="{{ url_for('buyers_page') }}">
    <div class="row">
      <div><label>Name</label><input name="name" required placeholder="Rental Fund LLC" /></div>
      <div><label>Entity type</label><input name="entity_type" value="LLC" /></div>
      <div><label>Primary contact</label><input name="primary_contact" placeholder="Jacob Patel" /></div>
    </div>
    <div class="row">
      <div><label>Email</label><input name="email" type="email" placeholder="jacob@midsouth.com" /></div>
      <div><label>Phone</label><input name="phone" placeholder="(901) 555-1234" /></div>
      <div><label>Preferred channel</label>
        <select name="preferred_channel">
          <option value="email">email</option><option value="call">call</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div><label>Zip codes (comma-separated)</label><input name="zip_codes" placeholder="38127, 38109, 38118" /></div>
      <div><label>ARV min</label><input name="min_arv" type="number" placeholder="55000" /></div>
      <div><label>ARV max</label><input name="max_arv" type="number" placeholder="140000" /></div>
    </div>
    <div class="row">
      <div><label>Max repair % of ARV</label><input name="max_repair_pct" type="number" step="0.05" placeholder="0.30" /></div>
      <div><label>Min beds</label><input name="min_beds" type="number" placeholder="2" /></div>
      <div><label>POF amount</label><input name="pof_amount" type="number" placeholder="400000" /></div>
    </div>
    <button class="primary" type="submit">Add buyer</button>
    <span class="hint" style="margin-left: 1rem;">Fields left blank won't restrict matches.</span>
  </form>
</div>

</body>
</html>
"""


@app.route("/buyers", methods=["GET", "POST"])
def buyers_page():
    conn = get_db()
    if request.method == "POST":
        form = request.form
        data = {
            "name": form["name"],
            "entity_type": form.get("entity_type") or "LLC",
            "primary_contact": form.get("primary_contact") or None,
            "email": form.get("email") or None,
            "phone": form.get("phone") or None,
            "preferred_channel": form.get("preferred_channel") or "email",
            "zip_codes": form.get("zip_codes") or None,
            "min_arv": float(form["min_arv"]) if form.get("min_arv") else None,
            "max_arv": float(form["max_arv"]) if form.get("max_arv") else None,
            "max_repair_pct": (float(form["max_repair_pct"])
                               if form.get("max_repair_pct") else None),
            "min_beds": int(form["min_beds"]) if form.get("min_beds") else None,
            "pof_amount": (float(form["pof_amount"])
                           if form.get("pof_amount") else None),
            "pof_on_file": 1 if form.get("pof_amount") else 0,
        }
        db_module.insert_buyer(conn, data)
        flash(f"added {data['name']}")
        return redirect(url_for("buyers_page"))

    buyers = db_module.list_buyers(conn)
    return render_template_string(BUYERS_TPL, buyers=buyers)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@app.route("/import", methods=["POST"])
def import_csv():
    conn = get_db()
    f = request.files.get("csv")
    if not f:
        flash("no file")
        return redirect(url_for("queue"))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    f.save(tmp.name)
    tmp.close()

    def enrich(lead_dict):
        buyers = db_module.list_buyers(conn, zip_code=lead_dict.get("zip_code"))
        return count_matches(lead_dict, buyers)

    # Temporarily 45 during initial testing — raise to 70 after enrichment screen is built
    result = import_file(conn, tmp.name, score_threshold=45.0,
                         matching_buyers_fn=enrich)
    os.unlink(tmp.name)
    flash(f"imported {result.imported}, rejected {result.rejected} of {result.total}")
    return redirect(url_for("queue"))


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
