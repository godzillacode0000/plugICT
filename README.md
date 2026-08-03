# PlugICT — ICT Evidence Vault

**775 ICT videos. Searchable by your AI agent. Cited answers with timestamps.**

---

## Install

Tell your AI agent:

```
Install the ICT Knowledge Vault from godzillacode0000/plugICT
```

Your agent will:
1. Clone this repo
2. Ask for the path to the full `license.key` attachment — never paste its contents
3. Download and verify the encrypted vault
4. Install and smoke-test the local `plugict_search.py` runner
5. Read `PLUGICT-ICT-AGENT-SKILL.md` — it is included with the product, so no separate skill install is needed
6. Optionally configure MCP for agents that support it
7. You're done

---

## Ask

The default path is local and does not require MCP:

```bash
python plugict_search.py --query "What is FVG?" --format json
```

For a multi-facet question, repeat `--query` up to four times. The runner
returns bounded excerpts, timestamps, playlists, and YouTube deep links for
your AI agent to synthesize.

MCP remains available as an optional integration for supported clients.

---

## License

Your `license.key` is emailed after purchase. Keep it private — it's tied to your email.

Need help? Email `plugICTsupport@agentmail.to`.
