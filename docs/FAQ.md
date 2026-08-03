# ICT Knowledge Vault — FAQ

## General

**Q: What exactly is this?**
A: A searchable library of Inner Circle Trader YouTube videos — fully transcribed, indexed, and optimized for AI agent queries. Not raw files. Not PDFs. You can search by concept, keyword, or meaning.

**Q: Is this all of ICT's content?**
A: We've transcribed a broad library across 10 playlists from 2016-2026. This covers the major mentorship series (2022, 2023, 2024), lecture series (2025, 2026 SMC), charter content, forex series, and more.

**Q: Can I browse the raw transcript files?**
A: No. The vault is encrypted — you search and get results. Raw files are not extractable. This protects the content from unauthorized sharing.

**Q: Do I need an AI agent to use this?**
A: Yes — the product is designed for a terminal-capable AI agent. The default path is the local `plugict_search.py` runner, which returns bounded evidence and citations for the agent to synthesize. MCP is optional.

**Q: What AI agent do I need?**
A: Any agent that can run local Python commands and read JSON, including Hermes and similar terminal-capable agents. See `AI-AGENT-GUIDE.md`.

---

## Technical

**Q: Do I need internet?**
A: Search runs locally and PlugICT does not send your queries to a PlugICT cloud service. Internet is still needed for initial setup, downloading the verified release/dependencies, your AI agent, and YouTube deep links. Query execution does not require a PlugICT API.

**Q: How big is it?**
A: The exact size depends on the release build, but you only need about 500MB free disk space to install and run it.

**Q: Can I use this on Mac/Linux?**
A: Yes. Requirements: Python 3.10+, 4GB RAM.

**Q: Why is the first search slow?**
A: The encrypted vault and local retrieval runtime need to warm up on first use. The exact time depends on your machine. v3.6.7 does not require the old cross-encoder model.

**Q: How does the search work?**
A: The local runner uses the same licensed vault engine as the compatibility MCP server. It returns bounded evidence from keyword (FTS5), semantic (ChromaDB vectors), and knowledge-graph retrieval where available. Results are ranked by relevance, not just keyword match count.

**Q: Can I search by playlist?**
A: Yes. Use `--playlist` with the local runner, for example `python plugict_search.py --query "What does ICT say about FVG?" --playlist "2022 ICT Mentorship"`, or ask the optional MCP `search_ict` tool to apply the filter.

---

## License & Security

**Q: Can I share this with a friend?**
A: No. Your license key is unique and contains your email. Sharing is traceable to you.

**Q: What if I lose my license key?**
A: Contact us with your purchase ID for a replacement.

**Q: Is there DRM?**
A: No. The vault is encrypted and your license key is required to decrypt. There's no phoning home. The protection is encryption + watermarking, not DRM.

**Q: Can I get updates?**
A: Future updates may include new transcripts, features, and content. Purchase includes the current vault version.

---

## Content

**Q: Are these official ICT transcripts?**
A: These are automated transcriptions of publicly available YouTube videos from the Inner Circle Trader channel. They are not official or endorsed by ICT.

**Q: What's the transcription quality?**
A: High. Transcribed using faster-whisper (medium model). Timestamps are included. Minor errors possible in fast speech or overlapping audio.

**Q: Can I contribute or request specific videos?**
A: Not currently. This is a curated product.

**Q: What's the Knowledge Graph?**
A: We've extracted ICT concepts (FVG, Order Block, Silver Bullet, etc.) and their relationships. You can explore concept connections beyond simple search.

---

## Support

**Q: Something's not working.**
A: Check:
1. You supplied the full private `license.key` file to setup — not only a `LICENSE_ID` or `PURCHASE_ID`
2. Python 3.10+ is installed (`python --version`)
3. Rerun `python setup.py --license /path/to/license.key` so setup can recreate the isolated `.venv`, verify the release, and run doctor/direct-search checks
4. Run `python plugict_search.py --doctor` and send the reported error to support; do not manually delete vault/runtime folders or install PlugICT into global Python

**Q: How do I contact support?**
A: Email `plugICTsupport@agentmail.to`.

**Q: Refund policy?**
A: If the product has a genuine defect and we cannot resolve it within 7 days of purchase, you are entitled to a full refund. See `refund.html` for the qualifying cases and process.
