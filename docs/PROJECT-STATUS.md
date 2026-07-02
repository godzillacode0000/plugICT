# ICT Vault — Engineering & Launch Status

A single record of what was broken, what was fixed, how, and what's next.
Last updated after the "MCP-only" pivot. Test suite: **34 passing**.

---

## 1. What ICT Vault is

An AI knowledge base of **576 ICT videos** — transcribed, indexed, and made
searchable by the buyer's **own AI agent** over **MCP** (Model Context
Protocol). The buyer asks their agent (Claude Desktop, Cursor, Hermes, or any
MCP-compatible client) a question in natural language; the agent calls the
vault's tools and answers with **exact video sources and timestamps**.

- **Local-first**: the vault runs on the buyer's machine (encrypted). No cloud,
  no API key from us, no per-query fee.
- **Pay-once lifetime** license, tied to each buyer and traceable.
- **Malaysia-first payments**: DuitNow QR / FPX (Billplz), Stripe, USDT.

---

## 2. Critical repairs (were broken → now fixed)

### 2.1 The MCP server could not start at all 🔴
**Problem:** The flagship "connect your AI agent" feature was 100% non-functional:
- referenced an undefined `encrypted` variable → `NameError` on first tool call;
- imported `InitializationCapabilities` (does not exist in the MCP SDK);
- printed banners to **stdout**, corrupting the JSON-RPC channel;
- used the wrong FTS column for snippets (showed playlist text instead of content).

**Solution:** Rewrote `mcp_server.py` on the shared core. Correct
`InitializationOptions` + `get_capabilities`; all diagnostics to **stderr**;
correct snippet column. Proven by an **automated subprocess handshake test**
(initialize → discover tools → call tools → results).

### 2.2 Duplicated decrypt logic caused silent drift 🔴
**Problem:** `query.py` and `mcp_server.py` each had their own copy of the
decrypt/license logic. The MCP copy had drifted into the broken state above.

**Solution:** Extracted **`scripts/vault_core.py`** as the single source of
truth (license, decrypt, format, glossary, search session, FTS, temp hygiene,
doctor). Every tool imports from it, so the logic can never diverge again.

### 2.3 Failures were swallowed silently 🔴
**Problem:** `except: pass` everywhere hid real errors. Example: ordinary input
with punctuation (`buy-side liquidity`, `what's an order block?`) made the FTS5
`MATCH` raise, which was silently swallowed → the user got **zero results** and
assumed the vault was empty.

**Solution:** `vault_core.sanitize_fts()` quotes every token (OR-joined,
stopwords dropped, `ORDER BY rank`); every `except` now reports to stderr with a
clear, actionable message. Buyer-facing errors name the fix ("place license.key
next to mcp_server.py", the exact `pip install` line, etc.).

---

## 3. Architecture, performance, security

### 3.1 Decrypt once, not per query
**Problem:** The original design decrypted the entire ~400 MB vault on **every
query** (~30 s + a large RAM spike each time).

**Solution:** The MCP server decrypts **once at startup** and stays resident;
`VaultSession` (in `vault_core`) does the same for the benchmark harness.
Per-query cost after warm-up is ~1–3 s, dominated by the reranker, not
decryption. Added a **streaming decrypt** (chunked, low RAM) and a warm-up
progress line so the one-time unlock isn't mistaken for a hang.

### 3.2 Vault format v2 (zstd)
**Problem:** ~406 MB download.

**Solution:** Compress the payload with **zstd before encryption** (format v2,
version-negotiated, still reads v1). Expect a materially smaller artifact.
`vault_core.pack_and_encrypt()` owns the format so build and load stay in sync.

### 3.3 Security hardening
- Streaming decrypt + **SHA-256 integrity check** from the license.
- **Temp hygiene**: sweep stale plaintext dirs on startup, signal handlers, and
  tar extraction hardened against **path traversal and symlink/hardlink**
  entries on all Python versions (not just 3.12+).
- Corrected an overstated claim: a leaked license exposes the shared vault key —
  the real protection is **traceability**, not per-buyer isolation. (True
  per-buyer vaults remain an optional future upgrade.)

### 3.4 Correctness fixes
- YouTube results now **deep-link to the exact timestamp** (`?t=SECONDS`).
- Cache key includes `top_k` + vault hash (auto-invalidates on a new vault) with
  eviction.
- Query expansion only expands **user-typed uppercase** acronyms (no more
  false-expanding "ms"/"bs" inside normal sentences).
- Real glossary "related terms" (same category) instead of the first N keys.
- De-duplicated the playlist-classification logic (was copied 3×, drifting).
- Removed dead `.master_key`; fixed the delivery README license-ID bug.
- Corrected content counts (365 → **576**).

---

## 4. Product direction locked in

- **AI-agent (MCP) only.** The CLI search tool (`query.py`) was **removed** from
  the product; its reusable search session moved into `vault_core` as
  `VaultSession`. Buyers get a conversational experience, not a command line.
  Install verification survives via **`python mcp_server.py --doctor`**.
- **5 MCP tools**: `search_ict`, `explore_concept`, `list_playlists`,
  `vault_stats`, `glossary_lookup` (instant acronym → definition).
- **Free demo vault** (try-before-buy): `store/build_demo.py` builds a small,
  watermarked (`DEMO 5/576`) vault with a bundled license, reusing the real
  pipeline. The watermark is baked into the encrypted vault (not editable client
  code) and surfaces in both the agent output and the health check.

---

## 5. Store & delivery (local / lifetime)

| File | Purpose |
|---|---|
| `scripts/build.py` | Build the encrypted vault (zstd v2); `ICT_DEMO=1` stamps a demo watermark |
| `scripts/generate_key.py` | Mint a per-buyer, envelope-encrypted `license.key` |
| `scripts/deliver.py` | Assemble the buyer package (MCP files only, venv installer, example configs) |
| `store/issue_license.py` | Turn a paid order into a `license.key`, logged to a ledger, optionally emailed |
| `store/webhook_server.py` | Automated issuance on purchase (Billplz / Stripe / Lemon Squeezy / Gumroad) with signature verification |
| `store/emails.py` | Branded license-delivery + manual-payment templates |
| `store/build_demo.py` | Build the free demo package |
| `store/README.md` | The delivery playbook |

**Key delivery insight:** the encrypted vault is safe to **host publicly once**
(useless without a license); only the tiny per-buyer `license.key` is unique.

---

## 6. Landing page

`index.html` (repo root, for GitHub Pages) + `getting-started.html`. Premium
dark design: animated grid, mouse glow, typing terminal demo, animated
knowledge graph, count-up stats, glass pricing card (struck anchor price → launch
price), accordion FAQ, payment badges. Self-contained, no build step, Product
JSON-LD schema, AA contrast, `prefers-reduced-motion` + no-JS fallbacks.
Verified in headless Chromium (desktop + mobile).

---

## 7. Testing (0 → 34)

`tests/` covers: vault round-trip (v1 + v2), corrupted/wrong-license rejection,
MCP handshake (5 tools), full seller pipeline (build → generate_key → open),
demo watermark, license issuance + distinct keys, webhook parsing/signatures
(incl. Billplz), email templates, FTS sanitisation, query expansion, timestamp
deep-links, tar traversal/symlink rejection, glossary. Plus a **20-query
search-quality benchmark** (`tests/benchmark_queries.json`) and a seller-side
runner (`tests/run_benchmark.py`) to catch quality regressions.

> Note: `chromadb` / `sentence-transformers` aren't installed in the CI sandbox,
> so the semantic + rerank legs are exercised via fixtures; real numbers must be
> measured on the real vault (see §9).

---

## 8. Known issues / cleanup

- **Duplicate landing page**: `index.html` (root) and `landing/index.html` both
  exist and can drift. Pick one source of truth (recommend keeping root for
  Pages, deleting `landing/index.html` or generating it).
- **Placeholder links**: `data-buy-link` (checkout) and `data-demo-link` need
  real URLs before launch.
- **Dependency pins** are compatible-release (`~=`), validated only against the
  light deps; lock exact versions after one clean install with the heavy deps.
- **JSON-LD vs visible price**: keep the schema `price` in sync with the
  displayed price whenever it changes.

---

## 9. Owner action items (not code — only you can do these)

1. **Content-rights / naming decision.** Selling transcripts of a third party's
   videos is the real launch gate; "ICT" in the product name adds trademark
   exposure. This blocks safe scaling — especially any hosted connector.
2. **Build the real 576-video vault** and run `python tests/run_benchmark.py`
   against it to get real per-query latency + quality numbers.
3. **Wire real payment accounts** (Billplz X-Signature key, Stripe keys, USDT
   wallet, DuitNow QR) and host the vault zip + demo zip; fill the two
   placeholder links.
4. **Lock exact dependency versions** after one clean `setup.bat` on a real
   machine.

---

## 10. Roadmap — next phases

### Phase A — Launch hardening (before first sale)
- Resolve §9 items 1–4.
- Delete the duplicate landing file; sync JSON-LD price.
- Add a CI workflow (`pytest` on every push) so stale-tree regressions can't
  reappear.

### Phase B — First post-launch update
- **Bundle the embedding + reranker models** in the package so the *first*
  search is fully offline too (today it downloads ~180 MB once).
- Per-buyer vault re-encryption + watermarking (true isolation + leak tracing).
- Vault content-update / re-download flow.

### Phase C — Reach cloud-AI users
- **Hosted MCP connector** so ChatGPT-web and Claude.ai-web can connect via a
  URL + key. Unlocks the largest audience and a subscription tier — but requires
  hosting the content, so it is gated on the rights decision (§9.1).

### Phase D — Efficiency / scale
- Migrate ChromaDB → `sqlite-vec` to collapse the vault to a single SQLite file
  (drops a heavy dependency, shrinks the artifact, removes the tar step).
- PyInstaller one-file distribution to eliminate the Python-install support
  burden entirely.

---

*This document reflects the state on the default branch. Update it as phases
land so it stays the single source of truth.*
