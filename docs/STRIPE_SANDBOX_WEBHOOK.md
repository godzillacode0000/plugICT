# Public Stripe sandbox buyer-fulfilment runbook

This runbook proves one **zero-real-money** path end to end:

```text
Stripe sandbox Payment Link ($18.99 USD, test funds only)
  -> public HTTPS webhook on Render
  -> buyer-specific license issuance
  -> AgentMail delivery to kevingenautry@gmail.com
```

It is isolated from the existing service: use `render.sandbox.yaml`, which creates
`plugict-webhook-sandbox`. **Do not select `render.yaml`, rename the live
service, copy sandbox secrets into a live service, or switch this service to
live mode.** No deploy is performed by the repository tests.

Passing this exercise is evidence for the sandbox path only. It is **not
production payment proof**, production durability proof, or approval to enable
real-money fulfilment.

## 1. Prepare the Stripe sandbox Payment Link

In the Stripe Dashboard, select the intended **sandbox/test environment** before
creating anything.

1. Create a one-time product/price for exactly **USD $18.99**.
2. Create a Payment Link for that one price.
3. Require customer email collection.
4. Disable promotion codes, optional items, and adjustable quantity. The buyer
   must not be able to alter quantity; verify the rendered Checkout page shows
   exactly one item and `$18.99` before continuing.
5. Record the Payment Link ID (`plink_...`) for
   `STRIPE_PAYMENT_LINK_ID` and its sandbox URL for the test purchase.

### Line-items / quantity limitation

The webhook intentionally validates the signed Checkout Session fields available
in the event: exact Payment Link ID, `amount_total=1899`, `currency=usd`, status,
payment status, both livemode flags, and buyer allowlist. It does **not** fetch or
expand `line_items`, and therefore does not independently inspect quantity.
Before every manual E2E, the operator must verify in Stripe that this exact
Payment Link has one fixed-price item, quantity fixed at one, and no adjustable
quantity. Provider-side Payment Link configuration is part of the evidence.
Do not treat amount matching alone as quantity verification.

## 2. Create only the sandbox Render service

1. In Render, create a new Blueprint from this repository.
2. In **Blueprint Path**, enter `render.sandbox.yaml` (Render otherwise defaults
   to the root `render.yaml`).
3. Review the proposed resource list and require exactly one web service named
   **`plugict-webhook-sandbox`**. Cancel if Render proposes changing
   `plugict-webhook` or any existing/live resource.
4. Supply the dashboard-only values marked `sync: false`:

   | Variable | Required sandbox value |
   |---|---|
   | `WEBHOOK_SECRET` | The signing secret for the sandbox webhook endpoint created in section 3; never a Stripe API key |
   | `STRIPE_PAYMENT_LINK_ID` | Pinned to sandbox link `plink_1TyYisGZluauKOWaPlRObjdi` |
   | `AGENTMAIL_API_KEY` | A test-scoped AgentMail key, entered only in Render |
   | `AGENTMAIL_INBOX` | Preconfigured as `orders-test@agentmail.to` |

5. First run the normal offline seller integrity gate against the canonical
   `ict-vault.kevin`: its SHA-256 must exactly match `.vault_sha256`, and the
   canonical owner licence must still open that vault. Then add only two small
   Render Secret Files at `/etc/secrets/.vault_key` and
   `/etc/secrets/.vault_sha256`. Render Secret Files have a 1 MB total limit,
   so the ~200 MB encrypted vault must not be uploaded there. Never read either
   secret file into logs, screenshots, chat, or Git.
6. Deploy. Startup fails closed unless every required variable exists, the
   sandbox values are exactly `false`, `1899`, `usd`, and `agentmail`, the buyer
   allowlist contains `kevingenautry@gmail.com`,
   `ICT_VERIFY_SOURCE_VAULT=false`, and both seller artefacts exist and have
   valid sizes/formats under `ICT_SOURCE_DIR`. Hash-only issuance is permitted
   only in explicit sandbox mode; all other modes retain full vault re-hashing.
7. Open `https://<sandbox-service>.onrender.com/health`. The entire response must
   be exactly:

   ```json
   {"ok":true}
   ```

The health route does not expose mode, provider, paths, email addresses,
credentials, Stripe IDs, or artefact details.

## 3. Register the public Stripe sandbox webhook

Still in the same Stripe sandbox/test environment:

1. Open Workbench/Developers -> Webhooks and add a public HTTPS endpoint:
   `https://<sandbox-service>.onrender.com/webhook/stripe`.
2. Subscribe only to `checkout.session.completed`.
3. Copy that endpoint's sandbox signing secret (`whsec_...`) into the sandbox
   Render service's `WEBHOOK_SECRET`; do not paste it into a command, document,
   issue, chat, or Git.
4. Redeploy and repeat the exact `/health` check.

The endpoint rejects non-Stripe provider routes. For Stripe it accepts only a
correctly signed `checkout.session.completed` whose top-level Event and embedded
Checkout Session both have `livemode=false`, with Session `status=complete`,
`payment_status=paid`, the exact Payment Link, 1899 amount, `usd`, a Session ID,
and the allowlisted buyer email.

## 4. Execute the zero-money purchase

1. Open the **sandbox** Payment Link URL directly. Do not use any production
   landing-page checkout link.
2. Enter `kevingenautry@gmail.com` as the buyer.
3. Complete Checkout with a Stripe test payment method (for example Stripe's
   documented test card `4242 4242 4242 4242`, any future expiry, any CVC).
   Test mode creates no real charge and must show `livemode=false` in evidence.
4. In Stripe, open the resulting `checkout.session.completed` Event. Confirm:
   - Event `livemode` is `false`;
   - Session `livemode` is `false`;
   - `status=complete` and `payment_status=paid`;
   - `payment_link` equals the configured `plink_...`;
   - `amount_total=1899`, `currency=usd`;
   - customer email is `kevingenautry@gmail.com`.
5. Confirm the delivery attempt received HTTP 2xx with `{"status":"issued"}`.
6. Confirm AgentMail reports one sent message and the Gmail inbox
   `kevingenautry@gmail.com` receives one PlugICT email with one `license.key`
   attachment. Record only safe message/thread IDs, not attachment contents or
   credentials.

No test or local command in this repository sends this message; the only real
send in this runbook is the owner-authorized sandbox checkout through the
manually configured public service.

## 5. Dashboard resend / duplicate evidence

1. In the Stripe Dashboard, open the same sandbox Event and its delivery to the
   sandbox endpoint.
2. Use **Resend** for that same Event/destination.
3. Require HTTP 2xx with
   `{"status":"duplicate","order_id":"cs_test_..."}`.
4. Confirm AgentMail still reports one message for that Session and Gmail did
   not receive a second licence email.

The webhook holds a dependency-free process lock around duplicate check plus
issuance, which suppresses sequential and concurrent duplicates on one running
Python instance. This is **not crash/restart durability**: Render's free
filesystem is ephemeral, the lock disappears on restart, multiple instances do
not share it, and a crash after email send but before ledger append can produce
a later duplicate. `ICT_ISSUED_DIR` and `ICT_ISSUED_LEDGER` make paths
configurable; they provide durability only when pointed at operator-provisioned
shared/persistent storage. The default paths remain `store/issued` and
`store/issued_licenses.csv` outside this sandbox blueprint.

## 6. Evidence checklist

Keep a redacted evidence bundle with:

- [ ] Git branch/revision and unchanged `render.yaml` confirmation.
- [ ] Render Blueprint path `render.sandbox.yaml` and service name
      `plugict-webhook-sandbox`.
- [ ] Environment key names and non-secret fixed values only; no secret values.
- [ ] Redacted proof that both Secret File names exist under
      `ICT_SOURCE_DIR` (never their contents).
- [ ] Exact safe health response `{"ok":true}`.
- [ ] Stripe sandbox Payment Link settings showing $18.99 USD, one fixed item,
      non-adjustable quantity, and the configured Payment Link ID.
- [ ] Stripe Event ID and Session ID with both `livemode=false`, paid/complete,
      exact link/amount/currency, and controlled buyer.
- [ ] Initial webhook 2xx `issued` response.
- [ ] Safe AgentMail message/thread IDs plus receipt in
      `kevingenautry@gmail.com`; no license contents.
- [ ] Dashboard resend 2xx `duplicate` response and evidence of no second email.
- [ ] Explicit label: **SANDBOX E2E ONLY — NOT PRODUCTION PROOF**.

## 7. Negative checks (optional but recommended)

Use synthetic/local automated tests—not real purchases—to show that live-mode
flags, wrong link, wrong amount, wrong currency, wrong email, wrong event type,
and non-Stripe providers do not issue. Do not mutate the controlled public Event
or send secrets to third-party request tools. The repository command is:

```bash
python -m pytest tests/test_sandbox_webhook.py -q
```
