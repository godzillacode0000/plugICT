# Cloudflare Pages + D1 operations (Gate B preview)

This document is the operational contract for the **preview-only** affiliate analytics data plane. It does not authorize DNS changes, production D1, production beacon activation, Stripe writes, payouts, or buyer fulfilment automation.

## Components

| Component | Role | Current state |
|---|---|---|
| GitHub Pages | Current canonical public host | Unchanged |
| Cloudflare Pages Functions | `/api/health`, affiliate click/stats routes | Preview code only |
| D1 `affiliate_codes` | Affiliate code/status/token-hash mirror | Local/preview only |
| D1 `affiliate_clicks` | Deduplicated privacy-safe click events | Local/preview only |
| Retention Worker | Daily bounded delete of clicks older than 90 days | Preview config only |
| Stripe + local SQLite | Financial authority | Read-only / unchanged |
| Cloudflare Web Analytics | General traffic analytics | Not activated by Gate B |

D1 is **not** the financial ledger. It must never receive buyer email, raw IP, raw user-agent, Stripe IDs, commission amounts, payout status, or raw browser visitor IDs.

## Local setup

Run from the repository root:

```bash
npm run build:site
npx wrangler d1 execute plugict-affiliate-analytics-preview \
  --local --config wrangler.toml --file=cloudflare/schema.sql
```

Use a local-only salt through an ignored `.dev.vars` file. Start the static site and Functions preview only when needed:

```bash
npx wrangler pages dev dist --config wrangler.toml --local
```

The public frontend configuration must remain:

```javascript
window.PLUGICT_AFFILIATE_API = '';
```

Gate B tests and local preview can call the API directly without changing that production/static config.

## Preview D1

A remote D1 database may be created only with a preview name such as `plugict-affiliate-analytics-preview`. Apply schema explicitly:

```bash
npx wrangler d1 create plugict-affiliate-analytics-preview
npx wrangler d1 execute plugict-affiliate-analytics-preview \
  --remote --file=cloudflare/schema.sql
```

Store the resulting non-secret database ID in the private preview deployment configuration only. Do not use a production database name or `--remote` against production during Gate B. Protect a preview deployment with Cloudflare Access where practical; Access credentials are never stored in this repository.

## API contracts

### `GET /api/health`

Returns a non-sensitive service marker:

```json
{"ok":true,"service":"affiliate-analytics","mode":"preview"}
```

### `POST /api/affiliate/click`

Accepts JSON encoded as `text/plain;charset=UTF-8` to avoid a browser preflight dependency:

```json
{
  "code": "test_001",
  "click_id": "browser-generated-id",
  "visitor_id": "browser-local-id",
  "path": "/",
  "referrer": "https://example.com/article"
}
```

Rules:

- only a fresh valid `?ref=` landing sends the event;
- later visits using stored checkout attribution do not send another click;
- unknown/paused/closed codes return the same empty `204` response;
- duplicate `click_id` is ignored;
- browser visitor ID is HMAC-SHA-256 hashed with a server-side salt;
- only the referrer hostname is stored;
- body is capped at 4 KiB;
- CORS is an origin convenience, not authentication;
- analytics failure must not break checkout or page rendering.

### `GET /api/affiliate/stats`

Uses `Authorization: Bearer [REDACTED]` supplied through a password field and kept in `sessionStorage`. Tokens are never accepted from query strings. The response is aggregate-only and has `Cache-Control: no-store`.

Finance fields are explicitly unavailable until an authoritative read-only sync is designed:

```json
{
  "purchases": null,
  "conversion_rate": null,
  "pending_commission_cents": null,
  "paid_commission_cents": null,
  "voided_purchases": null,
  "finance_status": "not_connected"
}
```

The dashboard must render these as **Not connected**, never as zero.

## Owner read-only aggregate queries

There is no public `/api/owner/*` route and no owner token system. Kevin can inspect preview/production D1 privately through authenticated Wrangler access. Queries must select aggregates only:

```sql
SELECT affiliate_code, day,
       COUNT(*) AS clicks,
       COUNT(DISTINCT visitor_hash) AS approximate_visitors
FROM affiliate_clicks
WHERE created_at >= unixepoch('now', '-30 days')
GROUP BY affiliate_code, day
ORDER BY day DESC, affiliate_code;
```

Before running a query:

```bash
npx wrangler d1 execute plugict-affiliate-analytics-preview \
  --local --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
```

Do not print token hashes or row-level visitor hashes in reports. A unique visitor is an approximate browser-derived count, not an exact person count.

## Ledger → D1 mirror

Use the executable fail-closed operator:

```bash
python scripts/sync_affiliate_to_d1.py \
  --ledger C:/private/exact/affiliate_ledger.sqlite3 \
  --database plugict-affiliate-analytics-preview \
  --dry-run
```

The ledger path must already exist and resolve to a file. The script refuses a typo that would otherwise create a new empty ledger. It mirrors only affiliate code, display name, status, and token hash. It does not read or send Stripe/payment/sale/payout data.

Preview sync requires both flags:

```bash
python scripts/sync_affiliate_to_d1.py \
  --ledger C:/private/exact/affiliate_ledger.sqlite3 \
  --database plugict-affiliate-analytics-preview \
  --remote --confirm-preview
```

Token rotation is preview-only and rolls back the local ledger hash if the D1 sync fails:

```bash
python scripts/sync_affiliate_to_d1.py \
  --ledger C:/private/exact/affiliate_ledger.sqlite3 \
  --database plugict-affiliate-analytics-preview \
  --rotate test_001 --remote --confirm-preview
```

The resulting raw token is shown once by the command and must be delivered privately, never committed, logged into SQL, placed in HTML, or sent through a public URL. Revocation is performed by setting the local affiliate status to `paused` or `closed`, then syncing the status to preview D1.

## Retention Worker

`cloudflare/retention-worker/src/index.js` has only a scheduled handler. It has no public maintenance route. Each run:

- deletes from `affiliate_clicks` only;
- selects rows older than exactly 90 days;
- deletes at most 1,000 rows per batch;
- runs at most 5 batches per invocation;
- leaves `affiliate_codes` and all financial systems untouched.

Preview worker configuration is in `wrangler.retention.toml`.

## Disablement and rollback

To disable analytics without changing the site:

1. keep `assets/affiliate-config.js` empty;
2. stop/deploy no Functions preview route;
3. revoke/rotate preview tokens;
4. pause the retention Worker;
5. preserve the local SQLite ledger as the financial authority.

For a preview-only rollback, stop the preview Pages project/Worker and remove only preview D1 resources after exporting any non-sensitive aggregate evidence. Do not change DNS or the canonical GitHub Pages deployment as part of Gate B.

## Gate B exit checks

- [x] allowlisted static artifact still builds;
- [x] schema has only affiliate code/click analytics tables;
- [x] click payload validation, HMAC hashing, deduplication, and privacy tests pass;
- [x] retention age boundary, scope, and batch cap tests pass;
- [x] affiliate token auth and cross-affiliate isolation tests pass;
- [x] dashboard has session-only token handling and null finance rendering;
- [x] production beacon config remains empty;
- [ ] remote preview deployment and visual/mobile smoke remain environment-dependent until a preview project is created and protected;
- [ ] production activation remains a separate Gate D approval.
