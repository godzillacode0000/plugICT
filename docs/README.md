# ICT Knowledge Vault — Quick Start

## What You Got

A complete, AI-searchable library of **775 ICT (Inner Circle Trader) YouTube videos** — transcribed, indexed, and ready to query. **Hundreds of hours** of trading mentorship at your fingertips.

Not raw files. Not PDFs. **AI-searchable knowledge vault.**

---

## Setup (2 Minutes)

**Windows** — double-click `setup.bat`, or run `python setup.py --license "C:/path/to/license.key"`. It builds an isolated environment (`.venv`), installs everything, and refuses to report success until doctor and a live MCP search pass.

**macOS / Linux**
```bash
./setup.sh --license /path/to/license.key
```

A `LICENSE_ID` or `PURCHASE_ID` alone is not a license. Use the full `license.key` file from the purchase email.

Something not working? Run a health check:
```bash
.venv\\Scripts\\python -E -X utf8 mcp_server.py --doctor      # Windows
.venv/bin/python -E -X utf8 mcp_server.py --doctor          # macOS / Linux
```

---

## Connect Hermes

Run `python setup.py --license /path/to/license.key`. It prints and writes the exact MCP config block for this install. Paste that block under `mcp_servers` in your Hermes profile config and restart Hermes.

The generated config uses the buyer `.venv`, `-E -X utf8`, a 180-second cold-start timeout, and isolated temp/model-cache paths. The best default tool is `multi_search_ict`; it returns cited, capped snippets plus safe `result_ref` values for `expand_result` when more context is needed. Legacy `search_ict`, `explore_concept`, `glossary_lookup`, `list_playlists`, and `vault_stats` are also available.

Then just ask, in natural conversation:

> *"How does ICT teach the Silver Bullet entry in the New York session?"*

Your agent searches the vault and answers with cited sources and timestamps.
Full walkthrough: `docs/AI-AGENT-GUIDE.md`. Evidence rules for agents are in
this guide and `AGENTS.md`; no extra skill file is required for the buyer
install flow.

---

## What's Inside

| Component | What |
|---|---|
| 775 videos | 10 playlists, 2016-2026 |
| Hundreds of hours | Full transcriptions with timestamps |
| 21,985 semantic chunks | Timestamp-preserving search units |
| Keyword search | Find exact terms instantly |
| Semantic search | Find concepts by meaning, not just words |
| Knowledge Graph | 29 ICT concepts with 15 relationships |

---

## System Requirements

| Component | Minimum |
|---|---|
| Python | 3.10+ |
| RAM | 4GB |
| Disk | 500MB free |
| OS | Windows 10+, macOS 12+, Linux |

---

## Files

| File | Purpose |
|---|---|
| `ict-vault.kevin` | Encrypted vault (don't share) |
| `license.key` | Your unique license (don't share) |
| `mcp_server.py` | AI agent bridge (the app) |
| `docs/` | Full documentation |

---

## License

This product is licensed to a single user. Sharing is traceable. Support future updates by respecting the license.
