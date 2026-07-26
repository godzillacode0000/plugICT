# PlugICT Affiliate Analytics — Phase 1 + Phase 2

This document describes the merged affiliate attribution and dashboard implementation.

## What is shipped in the repository

### Phase 1 — deterministic attribution and ledger

- Affiliate registry with active/paused/closed states.
- SQLite sales ledger keyed by unique Stripe Checkout Session ID.
- Exact Payment Link validation before crediting a sale.
- `$5 USD` commission calculation.
- Refund/dispute disqualification and payout-state handling.
- Manual payout batching and paid-reference recording.
- Read-only Stripe reconciliation in `scripts/check_affiliate_sales.py`.
- Affiliate access-token issuance with SHA-256 hashes stored in SQLite.

### Phase 2 — self-service analytics

- `store/affiliate_portal.py`: FastAPI service for click ingestion and private stats.
- `assets/affiliate-analytics.js`: privacy-first referral click beacon.
- `affiliate-dashboard.html`: same PlugICT dark/green dashboard UI.
- Aggregate-only responses; buyer email/name data is never returned.
- Click deduplication by affiliate + click ID.
- Approximate unique clicks from an HMAC-hashed browser visitor ID.
- Stats: total clicks, unique clicks, purchases, conversion rate, pending/paid commission, voided purchases.

## Seller setup

### 1. Initialize the private ledger

```bash
python scripts/affiliate_ledger.py --db store/affiliate_ledger.sqlite3 init
python scripts/affiliate_ledger.py --db store/affiliate_ledger.sqlite3 add-affiliate CODE "Affiliate Name" --contact "@handle" --payout-method "bank"
python scripts/affiliate_ledger.py --db store/affiliate_ledger.sqlite3 issue-token CODE
```

The final command prints the private token once. Send it to the affiliate through a private channel. Never commit it, put it in HTML, or paste it into a public issue.

### 2. Configure the read-only Stripe monitor

Set these outside the repository:

```text
STRIPE_API_KEY=restricted_read_only_key
STRIPE_PAYMENT_LINK_ID=exact_live_plink_id
AFFILIATE_DB=store/affiliate_ledger.sqlite3
AFFILIATE_LOOKBACK=3600
```

The monitor fails closed if the exact Payment Link ID is missing. It never calls Stripe write endpoints.

### 3. Deploy the analytics API separately from GitHub Pages

GitHub Pages can serve the dashboard UI but cannot run the SQLite/FastAPI API. Deploy `store.affiliate_portal:app` to a private seller-side FastAPI host with HTTPS.

Required environment:

```text
AFFILIATE_DB=/secure/path/affiliate_ledger.sqlite3
CLICK_HASH_SALT=<long random value kept outside the repository>
AFFILIATE_ALLOWED_ORIGINS=https://plugict.com,https://godzillacode0000.github.io
```

Start command:

```bash
uvicorn store.affiliate_portal:app --host 0.0.0.0 --port ${PORT:-8787}
```

Do not use the old `render.yaml` webhook blueprint without reviewing its legacy notice and production secrets. The affiliate API must run with HTTPS and a persistent private disk/database.

### 4. Point the static site at the API

Edit only the public, non-secret URL in:

```text
assets/affiliate-config.js
```

Set:

```javascript
window.PLUGICT_AFFILIATE_API = 'https://your-api.example.com';
```

Do not put API keys, access tokens, Stripe secrets, webhook secrets, or buyer data in this file.

### 5. Controlled validation before recruiting affiliates

- Open `https://plugict.com/?ref=qa_001` and confirm the click API receives one event.
- Reload once and verify click IDs deduplicate correctly.
- Use a Stripe test-mode Checkout Session where supported, or mark the live-session gate pending rather than making an unapproved charge.
- Confirm the resulting paid Checkout Session contains `client_reference_id=qa_001`.
- Run the read-only monitor and confirm one pending `$5` commission.
- Verify a refund/dispute changes the sale to void/disqualified.
- Open the dashboard using the issued token and confirm only aggregate stats appear.

## Security boundaries

- GitHub Pages is public static hosting; it never receives affiliate tokens.
- The dashboard uses `Authorization: Bearer <token>` and `Cache-Control: no-store`.
- SQLite stores only the SHA-256 hash of the affiliate access token.
- Click ingestion stores an HMAC hash of the browser visitor ID, not the raw visitor ID, IP, or user-agent.
- Stripe remains read-only. Payouts are still manual.
- Dashboard responses intentionally omit buyer PII and Stripe session IDs.
- Unknown or paused affiliate codes receive the same empty click response to reduce code enumeration.
