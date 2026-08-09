# PlugICT vault migration

## Canonical source and invariants

The encrypted PlugICT vault already contains the production search index. The
cloud migration **must not** re-chunk or re-embed transcripts.

Validated release contract:

- `775` authoritative transcript source rows / unique `source_file` values
- `774` unique YouTube video IDs
- `775` immutable R2 transcript objects
- `21,899` `semantic-v3.0.0` chunks in SQLite/FTS5
- `21,376` active persisted HNSW vectors
- `523` chunks intentionally available through FTS5 only
- `BAAI/bge-small-en-v1.5`, revision
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`
- normalized `384`-dimension vectors
- query contract `bge-v1.5-no-query-instruction-v1`
- `0` active-vector metadata gaps, missing FTS rows, or text mismatches
- uniform Chroma document binding: every vector carries the original
  `chroma:document` equal to its FTS text, or none do (the equivalent
  cryptographic `content_hash` binding is enforced on every vector); a mixed
  state is refused at export and at manifest validation

The row/video difference is intentional. Video `UQo4v1DREuU` has two distinct
source filenames with different transcript bodies. Neither row is silently
chosen or overwritten. Chunks map exactly to their own `source_file`.

## Immutable source-specific R2 identity

`video_id` is **not** an R2 object identity. Each transcript row receives a
content-addressed key:

```text
transcripts/by-source/<sha256(source_file + NUL + exact_content)>.md
```

This preserves all 775 source rows, prevents duplicate-video overwrites, and
lets D1 switch to a new immutable object only after that object exists.

## Export

Use the isolated vault environment:

```bash
unset PYTHONPATH
export ICT_OPEN_VAULT_BYPASS=1
export HF_HOME="D:/PlugICT/plugICT-install-test/.hf-home"
export ICT_TEMP_DIR="D:/PlugICT/plugICT-install-test/.tmp"

"D:/PlugICT/plugICT-install-test/.venv/Scripts/python.exe" \
  scripts/export_existing_vault.py --stage export \
  --export-dir cloudflare/ingest-existing
```

The exporter reads the persisted Chroma HNSW files directly and writes:

- `chunks.ndjson` — all 21,899 exact chunks and provenance
- `vectors.ndjson` — all 21,376 existing active vectors
- `transcripts.ndjson` — 775 exact source snapshots with `source_file`,
  `video_id`, immutable `r2_key`, and content
- `export-report.json` — written last and hash-binding every artifact

These generated artifacts are local-only and ignored by Git.

## Local fail-closed validation

Validation does not open the vault and performs no cloud writes:

```bash
python scripts/export_existing_vault.py --stage validate \
  --export-dir cloudflare/ingest-existing
```

Validation rejects before upload when any of these differ:

- artifact presence, byte size, or SHA-256;
- release counts or chunk/vector ID parity;
- chunk text/content hashes or chunker version;
- vector dimension, finite values, metadata, model, revision, normalization,
  query instruction, or schema version;
- source-file parity, source/video mapping, R2 key derivation, or R2 key
  uniqueness;
- report completeness or expected invariants.

Every upload mode, including `--r2-only`, executes the same validation before
its first cloud write. Uploads run from a single in-memory snapshot of the
artifacts read **before** validation: files mutated after validation can never
influence what is uploaded, and any mutation before validation is caught by the
manifest hash bindings. There is no `--skip-r2` mode — R2-first is mandatory.

## Cloud destinations and upload order

- R2 bucket: `plugict-vault`
- Vectorize index: `plugict-vault-index` (`384`, cosine)
- D1 database: `plugict-chat-db`

A full upload runs in this order:

1. upload immutable R2 objects, verify the exact 775-object count;
2. upsert existing vectors, verify the exact 21,376-vector count;
3. apply/verify the D1 schema preflight;
4. publish D1 FTS/chunk rows and R2 pointers **last** and verify the exact
   21,899-chunk count.

Each stage aborts before the dependent stage starts if its count differs from
the validated manifest. This order prevents D1 from pointing at an object that
a partial run never uploaded. Stable IDs and immutable keys make retries
idempotent.

```bash
python scripts/export_existing_vault.py --stage upload \
  --export-dir cloudflare/ingest-existing \
  --r2-workers 4 \
  --r2-s3-creds "D:/secure/r2-credentials.json"
```

Direct S3 uploads are accepted only for the exact `plugict-vault` bucket on an
account-scoped `https://<32-hex-account>.r2.cloudflarestorage.com` endpoint.

### D1 schema preflight

Before any chunk row is published, the remote D1 database must have the release
schema (`cloudflare/chat-db-schema.sql`):

```bash
npx wrangler d1 execute plugict-chat-db --remote \
  --file cloudflare/chat-db-schema.sql
```

The schema is `CREATE TABLE IF NOT EXISTS`-safe: it creates
`chat_usage_scoped` (the active plan-scoped quota ledger) without touching or
reinterpreting any legacy `chat_usage` table, and `chat_log` records metadata
only — never question text, answers, tokens, emails, or OAuth payloads. After
the preflight, verify the table list and row counts before chunk upload.

### R2 free-tier headroom

The `9,000,000,000`-byte gate is a **per-run source cap** on the bytes this
migration uploads, not an account-wide quota. Before running the upload,
independently confirm the R2 account's existing object usage so the combined
total stays below Cloudflare's 10 GB free-tier ceiling.

## Verification requirements

Upload loop counts are not proof of remote correctness. Before release, query
remote D1/Vectorize/R2 and prove:

- D1: 21,899 chunks, correct vector flags, 775 source files, 774 videos, and
  source-specific R2 keys;
- Vectorize: 21,376 expected IDs and query-model compatibility;
- R2: all 775 manifest keys exist with manifest-matching body hashes/sizes;
- both duplicate-video source keys retrieve their own exact body;
- a real authenticated chat request retrieves timestamped evidence through the
  D1 → R2 mapping and rejects missing/malformed evidence.

No production deployment or live-domain change is part of the migration itself.
