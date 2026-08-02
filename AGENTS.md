# PlugICT — AI Agent Installation Guide

## Agent instructions

When a user asks to install PlugICT, follow this exact flow:

1. Clone the public repo and enter it:

   ```bash
   git clone https://github.com/godzillacode0000/plugICT.git
   cd plugICT
   ```

   If the folder already exists, do not create a second nested clone. Run the
   setup from the existing PlugICT folder.

   After entering the folder, read `PLUGICT-ICT-AGENT-SKILL.md`. It is the
   buyer-facing ICT answer protocol shipped with PlugICT; no separate Hermes
   skill installation is required.

2. Ask for the **path to the full `license.key` file**. Never ask the buyer to
   paste the license contents into chat. A `LICENSE_ID` or `PURCHASE_ID` alone
   is not a license and must be rejected.

3. Run the installer with the file path:

   ```bash
   python setup.py --license /path/to/license.key
   ```

   On Windows, an example is:

   ```text
   python setup.py --license "C:/Users/<name>/Downloads/license.key"
   ```

4. Let setup finish. It will:
   - validate the complete license envelope without printing secrets;
   - use a bundled vault when present, otherwise download the latest release;
   - verify the release SHA-256 before extraction;
   - create/use only the buyer-local `.venv`;
   - install dependencies with the buyer interpreter and block host `PYTHONPATH` leakage;
   - run `mcp_server.py --doctor`;
   - run a real MCP `search_ict` smoke query and require cited evidence;
   - generate Claude, Cursor, and Hermes config files.

5. Merge the generated top-level Hermes block into the active profile config.
   Do not append a duplicate `plugict` block. The generated config already
   includes:
   - the exact buyer `.venv` interpreter;
   - `-E -X utf8`;
   - a 180-second cold-start timeout;
   - isolated temp/model-cache paths.

6. Restart the AI agent and ask:

   > Search PlugICT: What is FVG in ICT?

   A working install returns cited video timestamps. If setup exits non-zero,
   treat the install as incomplete and show the reported error; do not claim it
   succeeded.

## Human buyer prompt

> Install PlugICT from `https://github.com/godzillacode0000/plugICT`. My full
> `license.key` file is in my Downloads folder. Do not print its contents.

## Troubleshooting

- `LICENSE_ID` / `PURCHASE_ID` only: request the full email attachment.
- `No module named mcp`: rerun `python setup.py --license ...`; do not install
  PlugICT requirements into the AI agent's global Python environment.
- MCP timeout on first connection: use the generated 180-second timeout; the
  encrypted vault may take 30–60 seconds to warm up on first use.
- Integrity/hash failure: the vault and license do not match. Re-download the
  official package or contact support; do not disable verification.
- Never run `vault_core.py --query`; vault queries are exposed through MCP
  tools (`search_ict`, `multi_search_ict`, `expand_result`).
