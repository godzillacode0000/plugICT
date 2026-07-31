# PlugICT — AI Agent Installation Guide

This file tells your AI agent how to install and configure PlugICT.

---

## For the AI Agent (read this)

When a user asks you to install PlugICT, follow these steps:

### Step 1: Clone & setup

```bash
git clone https://github.com/godzillacode0000/plugICT.git
cd plugICT
```

### Step 2: Run setup

```bash
python setup.py
```

This script will:
- Ask the user for their license key → pass the prompt through to the user
- Download the encrypted vault from GitHub Releases
- Place `license.key` in the correct location
- Install Python dependencies
- Run `--doctor` to verify everything works
- Print the MCP configuration

### Step 3: Capture the output

The script prints an MCP config block for Hermes, the Nous Research agent.
Show it to the user and tell them to add it to their Hermes profile config.

### Step 4: Verify

Ask the user to restart their AI agent, then test with:

> "Search PlugICT for: What is FVG?"

If they get a cited answer with timestamps, it works.

---

## For the human (buyer)

Tell your AI agent:

> "Install the ICT Knowledge Vault from godzillacode0000/plugICT"

That's it. The agent handles the rest.
