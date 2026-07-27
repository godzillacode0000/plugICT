# PlugICT Affiliate Operations

This is the seller-side operating flow for the SQLite affiliate ledger. Stripe access is **read-only**: the monitor reads Checkout Sessions and PaymentIntents/Charges; it never creates refunds, edits Payment Links, changes prices, or moves money.

## Files

- `scripts/affiliate_ledger.py` — SQLite schema, affiliate registry, commission ledger, and manual payout commands.
- `scripts/check_affiliate_sales.py` — read-only Stripe reconciliation monitor.
- `store/affiliate_ledger.sqlite3` — live local database (ignored by Git; never commit it).

## One-time setup

1. Create the ledger:

```bash
python scripts/affiliate_ledger.py init
```

2. Register each affiliate with a unique code:

```bash
python scripts/affiliate_ledger.py add-affiliate amir_001 "Amir" \
  --contact "@amir" --payout-method bank
```

3. Store the monitor configuration outside Git. Required values:

```text
STRIPE_API_KEY=[RESTRICTED READ-ONLY KEY]
STRIPE_PAYMENT_LINK_ID=plink_[THE LIVE PLUGICT PAYMENT LINK ID]
```

`STRIPE_PAYMENT_LINK_ID` is deliberately required. The monitor refuses to credit a sale when the expected PlugICT Payment Link is not configured.

## Run a read-only reconciliation pass

```bash
python scripts/check_affiliate_sales.py
```

The monitor:

- Reads recent Checkout Sessions from Stripe.
- Requires `status=complete` and `payment_status=paid`.
- Requires the exact configured PlugICT Payment Link ID.
- Reads refund/dispute state from the PaymentIntent's latest Charge.
- Matches `client_reference_id` to an active affiliate.
- Uses the Stripe Checkout Session ID as the idempotency key.
- Writes a `$5 USD` commission into SQLite once.
- Invalidates pending/batched commission after a later refund or dispute.
- Prints redacted operational events; buyer email is not sent to Telegram.

No output means no new actionable event.

Example events:

```text
AFFILIATE_SALE|amir_001|18.99 USD|5.00 USD|cs_...
AFFILIATE_UNKNOWN|unregistered_code|cs_...
AFFILIATE_DISQUALIFIED|amir_001|refunded|void|cs_...
```

## Review pending commissions

```bash
python scripts/affiliate_ledger.py pending
```

Example:

```text
PENDING|amir_001|Amir|3|15.00 USD
```

## Manual payout workflow

1. Review the pending summary and verify the payout destination with the affiliate.
2. Batch the affiliate's pending sales:

```bash
python scripts/affiliate_ledger.py create-payout amir_001 \
  --method bank --note "September payout batch"
```

3. Send the payment manually using your agreed method.
4. Mark the batch paid using the bank/PayPal reference:

```bash
python scripts/affiliate_ledger.py mark-payout-paid payout_[ID] \
  --reference "bank-transfer-reference"
```

The payout reference is required for an audit trail. The system does not send money automatically.

## Affiliate administration

```bash
python scripts/affiliate_ledger.py list-affiliates
python scripts/affiliate_ledger.py affiliate-status amir_001 paused
python scripts/affiliate_ledger.py affiliate-status amir_001 active
```

## Scheduling

The monitor is safe to schedule later with a local scheduler or Hermes cron, but this change does **not** create or start a cron job. Keep it stopped until the live Payment Link ID and a controlled Stripe test flow have been verified.

Before promotion/commission credit, prove one test session end-to-end:

```text
affiliate URL
→ client_reference_id in Checkout Session
→ exact PlugICT Payment Link ID
→ paid session
→ SQLite commission row
→ refund/dispute invalidation
→ manual payout batch
```

## Gate B Cloudflare preview operations

Gate B adds a preview-only Pages Functions + D1 analytics plane. It does not replace the SQLite ledger, Stripe read-only monitor, or manual payout flow.

- D1 stores affiliate code/status/token hashes and privacy-safe click events only.
- D1 never receives buyer email, raw IP, raw user-agent, Stripe IDs, commission amounts, payout state, or license data.
- Clicks are approximate operational analytics, not payout proof.
- The public beacon remains disabled until the separate hosting/activation gates are approved.
- Affiliate dashboard tokens are entered into a password field and held in session-only browser storage; query-string token bootstrapping is prohibited.
- Finance fields remain `null`/`Not connected` until an authoritative read-only sync is separately approved.

Apply local preview schema:

```bash
npm run build:site
npx wrangler d1 execute plugict-affiliate-analytics-preview \
  --local --config wrangler.toml --file=cloudflare/schema.sql
```

Mirror the exact existing private ledger path fail-closed:

```bash
python scripts/sync_affiliate_to_d1.py \
  --ledger C:/private/exact/affiliate_ledger.sqlite3 \
  --database plugict-affiliate-analytics-preview --dry-run
```

Remote execution is restricted to preview and requires explicit confirmation:

```bash
python scripts/sync_affiliate_to_d1.py \
  --ledger C:/private/exact/affiliate_ledger.sqlite3 \
  --database plugict-affiliate-analytics-preview \
  --remote --confirm-preview
```

The retention Worker deletes only click rows older than 90 days, in bounded batches, and has no public maintenance route. Do not schedule it through Hermes cron during Gate B.

## Disablement / rollback

Keep `assets/affiliate-config.js` empty to disable public collection. To roll back preview, stop the preview Pages/Worker deployment, revoke preview affiliate tokens, and leave GitHub Pages, DNS, Stripe, and the private SQLite ledger unchanged. Do not delete or alter the financial ledger as part of analytics rollback.
