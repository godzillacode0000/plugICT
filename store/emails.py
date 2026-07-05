"""
emails.py — Buyer-facing email + message templates
===================================================
Pure functions returning (subject, text_body, html_body) or plain strings, so
they're easy to test and reuse from issue_license.py, the webhook, or a manual
reply. Fill URLs via env vars (see store/README.md):

  ICT_VAULT_DOWNLOAD_URL     where the buyer downloads the vault+app zip
  ICT_GETTING_STARTED_URL    the getting-started page
  ICT_SUPPORT_EMAIL          where buyers reply for help
  ICT_DUITNOW_NOTE / ICT_USDT_WALLET   for manual payment instructions
"""

import os

BRAND = "PlugICT"
ACCENT = "#E8622C"  # ember, matches the landing page


def _cfg():
    return {
        "download": os.environ.get("ICT_VAULT_DOWNLOAD_URL",
                                   "https://github.com/godzillacode0000/plugICT/releases/latest"),
        "guide": os.environ.get("ICT_GETTING_STARTED_URL",
                                "https://godzillacode0000.github.io/plugICT/#setup"),
        "support": os.environ.get("ICT_SUPPORT_EMAIL", "hermesian0000@gmail.com"),
    }


# ── License delivery (sent when a license.key is issued, any payment method) ──
def license_email(buyer_email, license_id):
    c = _cfg()
    subject = f"🔌 Your {BRAND} license is ready"

    text = f"""Thanks for your purchase — welcome to {BRAND}!

You're about 3 minutes from asking your AI anything about ICT.

1) Download the vault + app:
   {c['download']}

2) Unzip it anywhere, then drop the attached license.key into that same
   folder (next to setup.bat).

3) Run setup:
   - Windows:      double-click setup.bat
   - macOS/Linux:  ./setup.sh
   Setup installs everything and writes a ready-to-use AI config for you.

4) Connect your AI agent (Claude Desktop, Cursor or Hermes):
   Open the examples/claude_desktop_config.json that setup just created —
   its file paths are already filled in for your machine — and copy its
   contents into Claude Desktop's config. Full walkthrough:
   {c['guide']}

5) Restart your AI agent, then ask it: "What is FVG?"
   You'll get an answer with the exact video and timestamp.

Your license ID: {license_id}
This license is tied to you and is traceable. Please don't share it.

Questions? Just reply to this email or write to {c['support']}.

Happy trading,
The {BRAND} team

— {BRAND} is an independent educational tool, not affiliated with or endorsed
by The Inner Circle Trader. Nothing here is financial advice.
"""

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
            max-width:560px;margin:auto;color:#1b1811;line-height:1.6">
  <h2 style="margin:0 0 6px">🔌 Welcome to {BRAND}</h2>
  <p style="color:#57503f;margin-top:0">Thanks for your purchase! You're about 3 minutes from asking
     your AI anything about ICT.</p>

  <ol style="padding-left:18px">
    <li><b>Download</b> the vault + app:<br>
        <a href="{c['download']}" style="color:{ACCENT}">{c['download']}</a></li>
    <li><b>Unzip</b> it anywhere and drop the attached <code>license.key</code> into that same folder
        (next to <code>setup.bat</code>).</li>
    <li><b>Run setup</b> — double-click <code>setup.bat</code> (Windows) or <code>./setup.sh</code>
        (macOS/Linux). It installs everything and writes a ready-to-use AI config for you.</li>
    <li><b>Connect your AI agent</b> — open the <code>examples/claude_desktop_config.json</code> that
        setup just created (paths already filled in for your machine) and copy its contents into
        Claude Desktop, Cursor or Hermes. <a href="{c['guide']}" style="color:{ACCENT}">Full walkthrough</a>.</li>
    <li><b>Restart your AI agent</b> and ask it <i>“What is FVG?”</i> — you'll get an answer with the
        exact video and timestamp.</li>
  </ol>

  <p style="background:rgba(232,98,44,.08);border-left:3px solid {ACCENT};padding:10px 14px;border-radius:0 8px 8px 0">
     <b>License ID:</b> {license_id}<br>
     <span style="color:#57503f;font-size:14px">Tied to you and traceable — please don't share it.</span></p>

  <p style="color:#57503f;font-size:14px">Need help? Reply to this email or write to
     <a href="mailto:{c['support']}" style="color:{ACCENT}">{c['support']}</a>.</p>

  <hr style="border:none;border-top:1px solid #e6ebf0;margin:22px 0">
  <p style="color:#8a8171;font-size:12px">{BRAND} is an independent educational tool, not affiliated
     with or endorsed by The Inner Circle Trader. Nothing here is financial advice.</p>
</div>
"""
    return subject, text, html


# ── Manual payment instructions (DuitNow QR / USDT) ──────────────────────────
def payment_instructions(method):
    """Text you send a buyer who chose a manual method, before they pay."""
    method = (method or "").lower()
    if method in ("duitnow", "duitnowqr", "qr"):
        note = os.environ.get("ICT_DUITNOW_NOTE",
                              "Scan the DuitNow QR below and pay the exact amount.")
        return (f"To complete your {BRAND} order via DuitNow QR:\n\n"
                f"{note}\n\n"
                "After paying, reply with your payment reference/screenshot and the email "
                "you want the license sent to. We'll email your license.key shortly.")
    if method in ("usdt", "crypto"):
        wallet = os.environ.get("ICT_USDT_WALLET", "<your USDT wallet address>")
        return (f"To complete your {BRAND} order with USDT (Solana or TRC20):\n\n"
                f"Send the exact amount to:\n  {wallet}\n\n"
                "Double-check the network (Solana or TRC20) before sending. After the transfer "
                "confirms, reply with the transaction hash and your email — we'll send your "
                "license.key once it's on-chain.")
    return (f"Thanks for choosing {BRAND}. Reply with your preferred payment method "
            "(DuitNow QR or USDT) and we'll send instructions.")
