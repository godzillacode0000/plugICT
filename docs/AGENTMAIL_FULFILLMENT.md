# PlugICT + AgentMail fulfilment

## What is live in this repository

`store/issue_license.py` can now send a buyer's generated `license.key` through
AgentMail while retaining the existing SMTP path as a fallback.

```text
verified/manual paid order
    ↓
store/issue_license.py
    ├── generates one buyer-specific license.key
    ├── renders the existing PlugICT delivery email
    ├── sends via AgentMail (or SMTP)
    └── records provider/message/thread/status in issued_licenses.csv
```

AgentMail is only the email transport. It does **not** verify Stripe payments,
issue refunds, calculate commissions, or replace the private fulfilment ledger.
The payment trigger must remain a verified Stripe event or an owner-confirmed
paid order.

## First safe test

The screenshot-created test inbox is:

```text
orders-test@agentmail.to
```

Use it only for development/testing. It is not a branded PlugICT sender.

1. Revoke the API key exposed in the screenshot.
2. Create a fresh AgentMail key.
3. Keep the fresh key in a local secret store; do not paste it into chat or git.
4. Copy `store/agentmail.env.example` to a private environment file and fill
   the key locally.
5. Set `AGENTMAIL_INBOX=orders-test@agentmail.to` for the test phase.
6. Run the non-payment delivery test below with a test buyer address.

The Python process reads `AGENTMAIL_API_KEY` from the environment only.

## Manual delivery command

The existing command remains the entry point:

```bash
PLUGICT_EMAIL_PROVIDER=agentmail \
AGENTMAIL_INBOX=orders-test@agentmail.to \
python store/issue_license.py buyer@example.com ORDER-TEST-001 --method stripe --email
```

On Windows PowerShell, use `$env:NAME=...` locally. Never put the real key in a
command saved to shell history if the shell history is shared.

The command will fail closed if the AgentMail key, inbox, attachment, or API
response is missing. A successful response must include both AgentMail's
`message_id` and `thread_id`.

## Ledger fields

New rows in `store/issued_licenses.csv` include:

- `email_provider`
- `email_message_id`
- `email_thread_id`
- `email_status`

Legacy six-column ledgers are upgraded in place before a new delivery is
recorded. The license contents are never written to the ledger.

## Production transition

Do not use `orders-test@agentmail.to` for real buyers. When custom-domain
sending is approved:

- outbound-only: use an AgentMail sender such as `orders@plugict.com`, keep
  Gmail's existing MX records, and use `AGENTMAIL_REPLY_TO` for human support;
- full AgentMail inbox: use a dedicated subdomain such as
  `orders@mail.plugict.com` and add only the DNS records AgentMail supplies.

Do not change root MX, SPF, DKIM, or DMARC records without a DNS audit first.

## What is intentionally not implemented yet

- the existing legacy webhook automatically uses this provider through the shared `issue_license.py` path when `PLUGICT_EMAIL_PROVIDER=agentmail`;
- an isolated public Stripe sandbox configuration and manual test runbook now
  exist in `render.sandbox.yaml` and `docs/STRIPE_SANDBOX_WEBHOOK.md`, but no
  deployment or external resource change is made by this repository work;
- no AgentMail webhook endpoint has been deployed;
- no production DNS change has been made;
- no real API key is stored in the repo;
- no automatic delivery is enabled until Stripe payment verification and the
  durable production ledger are connected.
