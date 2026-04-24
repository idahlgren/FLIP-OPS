# Wholesale tool

Internal deal-tracking tool for Memphis wholesale real estate.

One user, 1–2 deals per month, PropStream as data source.
Grassroots architecture: Flask + SQLite + Gmail SMTP.

## Project layout

```
wholesale-tool/
├── app.py                 Flask shell + routes + inline templates
├── auth.py                HTTP Basic Auth middleware
├── db.py                  SQLite schema + CRUD
├── scoring.py             Three-factor lead scoring
├── buyer_matching.py      Buyer buy-box matching
├── templates.py           Outreach templates
├── email_sender.py        Gmail SMTP sender
├── propstream_import.py   CSV → score → db pipeline
├── integration_test.py    End-to-end test
├── requirements.txt       Python deps
├── Procfile               Railway process
├── railway.json           Railway build config
├── .python-version        Python 3.11 pin
├── .gitignore             Git exclusions
└── README.md              This file
```

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000.

Auth and email default to disabled locally for development ease.
Set the env vars (below) in your shell to test them locally.

## Railway deployment

### One-time setup

1. **Connect the GitHub repo.** Railway → New project → Deploy from GitHub repo.
2. **Add a persistent volume** (critical — without it SQLite wipes on every deploy):
   Settings → Volumes → New Volume → mount at `/data`, size 1GB.
3. **Set environment variables:**

   | Variable           | Purpose                                     |
   |--------------------|---------------------------------------------|
   | `SECRET_KEY`       | Flask session secret                        |
   | `DB_PATH`          | `/data/wholesale.db`                        |
   | `APP_USER`         | Basic auth username                         |
   | `APP_PASS`         | Basic auth password                         |
   | `SENDER_NAME`      | His name (for outreach templates)           |
   | `SENDER_PHONE`     | His business phone                          |
   | `BUSINESS_NAME`    | LLC name                                    |
   | `BUSINESS_ADDRESS` | LLC mailing address                         |
   | `SMTP_USER`        | Full Gmail address (only when ready to send)|
   | `SMTP_PASS`        | Gmail app password (16 chars)               |
   | `SMTP_FROM_NAME`   | Name shown as sender                        |

   Generate `SECRET_KEY` with:
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

4. **Generate a domain:** Settings → Networking → Generate Domain.

### Gmail app password

1. myaccount.google.com → Security → enable 2-Step Verification
2. Search "App passwords" → create one for "Mail" → "Other: wholesale-tool"
3. Copy the 16-char password into Railway `SMTP_PASS`

Without SMTP_USER + SMTP_PASS the app still runs — the compose screen
logs messages without sending. Safer default during testing.

### Deploy

```bash
git push origin main
```

Railway auto-deploys in ~90 seconds. Watch the Deployments tab.

## Dev workflow

```bash
# Make changes
git add -A
git commit -m "what you changed"
git push

# Before pushing, verify locally
python app.py
# or run module tests
python integration_test.py
```

## Module smoke tests

Each module runs standalone:

```bash
python db.py                # creates test db, inserts a lead
python scoring.py           # scores 3 sample leads
python buyer_matching.py    # matches a lead to 3 sample buyers
python templates.py         # renders the probate email template
python email_sender.py      # checks SMTP config (no actual send)
python propstream_import.py # imports a synthetic CSV
python integration_test.py  # exercises everything together
```

## What's in

- Lead queue sorted by score
- Lead detail: score breakdown, buyer matches, conversation chain
- Outreach composer with templates pre-filled
- Manual "Log outbound" with optional Gmail send
- HTTP Basic Auth
- Buyer list + add-buyer form
- PropStream CSV import
- Stage advance
- Opt-out auto-detection on inbound replies

## What's not in (yet)

- LLM personalization of drafts
- Direct mail printing integration
- Phone call audio recording
- Deal room (contract-to-close)
- Weekly reporting emails
- Enrichment review screen (the 2-min per-lead review flow)
