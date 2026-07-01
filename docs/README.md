# ICT Knowledge Vault — Quick Start

## What You Got

A complete, AI-searchable library of **365 ICT (Inner Circle Trader) YouTube videos** — transcribed, indexed, and ready to query. **315+ hours** of trading mentorship at your fingertips.

Not raw files. Not PDFs. **AI-searchable knowledge vault.**

---

## Setup (2 Minutes)

### Option 1: Automatic
```
Double-click setup.bat
```

### Option 2: Manual
```bash
pip install -r requirements.txt
```

### Test It
```bash
python query.py "Fair Value Gap definition"
```

You should see results with timestamps, playlists, and sources.

---

## Two Ways to Use

### A. Command Line Search
```bash
python query.py "Silver Bullet London session"
python query.py "Order Block vs Breaker"
python query.py "how to trade FOMC"
```

### B. Connect Your AI Agent
```bash
python mcp_server.py
```

Then add the config from `examples/` to your AI agent:
- **Claude Desktop** → `examples/claude_desktop_config.json`
- **Cursor** → `examples/cursor_mcp.json`
- **Hermes Agent** → `examples/hermes_config.yaml`

Your AI agent can now query all 365 videos directly. See `docs/AI-AGENT-GUIDE.md`.

---

## What's Inside

| Component | What |
|---|---|
| 365 videos | 10 playlists, 2016-2026 |
| 315+ hours | Full transcriptions with timestamps |
| 19,341 chunks | Split for precise search |
| Keyword search | Find exact terms instantly |
| Semantic search | Find concepts by meaning, not just words |
| Knowledge Graph | 17 ICT concepts with relationships |

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
| `query.py` | CLI search tool |
| `mcp_server.py` | AI agent bridge |
| `docs/` | Full documentation |

---

## License

This product is licensed to a single user. Sharing is traceable. Support future updates by respecting the license.
