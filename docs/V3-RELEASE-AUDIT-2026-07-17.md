# PlugICT V3 Release-Candidate Audit — 2026-07-17

## Status

**RELEASE CANDIDATE REGATED FOR FINAL EXACT-TREE REVIEW — NOT PROMOTED TO PRODUCTION.**

The corrected V3 candidate passed index integrity, encrypted buyer-runtime, permanent golden, paired benchmark, packaging, rollback, full-test, and static gates. Production V2 remains untouched. Commit/push remains fail-closed until a fresh independent reviewer accepts the exact staged tree; replacing production V2 still requires separate owner approval.

## Candidate, package, and rollback

| Item | Path | Result |
|---|---|---|
| Corrected isolated build | `D:\PlugICT\releases\v3-rebuild-20260717` | Passed |
| Encrypted candidate | `D:\PlugICT\releases\v3-rebuild-20260717\ict-vault.kevin` | Passed |
| Candidate-bound owner test licence | isolated build directory | Passed; protected values redacted |
| Private buyer package source | `D:\PlugICT\releases\v3-rc-package-20260717\owner-v3-rc_at_plugict_local` | Passed |
| Extracted ZIP verification | `D:\PlugICT\releases\v3-rc-extract-verify-20260717` | Passed |
| Physical V2 rollback | `D:\PlugICT\releases\v2-20260716-110921` | Byte-identical to production V2 |
| Production V2 | `D:\PlugICT\ict-vault.kevin` | Untouched |

## Corpus and index integrity

| Check | Verified result |
|---|---:|
| Source transcript files | 581 |
| Playlists | 10 |
| V3 FTS rows | 14,757 |
| V3 Chroma vectors | 14,757 |
| FTS/Chroma chunk-ID parity | 14,757 identical IDs |
| Stable chunk-ID/content-hash validation | 14,757 passed |
| Resume manifest | Schema 2, index-bound build identity |
| Invalid timestamp ranges | 0 |
| Missing timing provenance | 0 |
| `next_segment_inferred` chunks | 14,176 |
| `unknown` end-precision chunks | 581 |
| Semantic boundary signals | 9,643 |
| Average chunk size | 1,482 characters |
| Knowledge-graph entities | 29 |
| Knowledge-graph relations | 15 |
| Encrypted candidate size | 124,018,325 bytes |
| Candidate SHA-256 vs `.vault_sha256` | Match |

Resume mode fails closed on corpus/configuration mismatch, embedding-dimension mismatch, missing or wrong collection build identity, unstable IDs, content-hash mismatch, chunker-version mismatch, and document mismatch. A clean build removes incompatible old vectors before publishing a new accepted resume manifest. Completion identity and count are stamped across the schema-2 manifest, Chroma metadata, and `kg.db` only after final FTS/Chroma ID parity succeeds. `build.py` additionally binds the master DB to a one-read transcript byte snapshot whose corpus hash matches the attestation, then rechecks the live source immediately before publication.

## Buyer-runtime checks

- Encrypted V3 opens using the candidate-bound licence.
- A stale V3 licence bound to the previous encrypted artifact is rejected.
- Candidate licence hash matches the actual encrypted artifact.
- Per-buyer delivery rejects a stale artifact hash or mismatched buyer/order identity before creating the package. It snapshots and hashes the exact vault bytes before package creation, copies only that private snapshot, rehashes the copied artifact, and writes the exact verified licence bytes.
- Search returned five real results with exact canonical YouTube deeplinks derived from stored `video_id` and `start_seconds`.
- `timing_precision`, `start_seconds`, and `end_seconds` survive storage, retrieval, finalisation, and MCP output.
- Research-bundle video, per-video character, and global character limits are enforced before appending evidence; reported counts equal emitted text.
- Chunk-level concept/lesson metadata is derived from stable full chunk text before query-centred snippet truncation.
- Answerability remains conservative and does not claim factual proof.
- `vault_identity()` loads buyer-facing `VAULT.md`.
- Extracted-copy `mcp_server.py --doctor`: exit 0.
- Production V2 fingerprint remained unchanged after all V3 operations.

## Private buyer ZIP

- ZIP: `D:\PlugICT\releases\PlugICT-V3-RC-owner-test-20260717.zip`.
- ZIP size: **124,110,300 bytes**.
- Contents: **17 entries**.
- Required assets verified: encrypted vault, private test licence, `mcp_server.py`, `vault_core.py`, `metadata_enricher.py`, `VAULT.md`, installers, requirements, docs, and examples.
- Extracted vault bytes match the isolated encrypted candidate exactly.
- Extracted runtime source matches the final repository runtime.
- Checksum `PlugICT-V3-RC-owner-test-20260717.zip.sha256` was written after the final ZIP byte and immediately verified; value is **[REDACTED]**.
- This ZIP contains a private owner-test licence and must **never** be uploaded publicly.

## Permanent golden retrieval

Case: `sb-001` — ICT Silver Bullet multi-facet question, `top_k=5`.

| Metric | Result |
|---|---:|
| Passed | Yes |
| Required facet coverage | 1.0 |
| Timestamp presence | 1.0 |
| Unique videos | 4 |
| Maximum results per video | 2 |
| Results | 5 |

The required definition, 10–11 AM New York window, FVG entry, and rules/invalidation facets all passed. Adjacent chunks are merged only when they support the same matched-query evidence; distinct facets retain their own complete chunk text, chunk ID, and timestamp.

## Independent A2 V2 versus V3 benchmark

Fresh reports used the same final runtime, frozen **49-query** specification, deterministic split, and single-search strategy. The set contains 47 answerable cases and two explicit no-answer controls; 17 cases are in the deterministic holdout.

Both encrypted vaults independently derived the same **581-item `(source_file, video_id)` inventory hash**. Production V2 predates content-manifest metadata, so exact transcript-byte equality cannot be claimed; V3 additionally carries its content-manifest hash. Artifact hashes are different, proving that separate encrypted indexes were opened.

| Overall metric | A2 V2 | V3 | Delta |
|---|---:|---:|---:|
| Lexical hit@1 | 0.5957 | 0.6809 | +0.0851 |
| Lexical hit@5 | 0.7872 | 0.8511 | +0.0638 |
| MRR | 0.6702 | 0.7443 | +0.0741 |
| nDCG@5 | 0.8593 | 0.8582 | -0.0010 |
| Timestamp provenance coverage | 0.0000 | 1.0000 | +1.0000 |
| No-answer accuracy | 0.5000 | 1.0000 | +0.5000 |
| Duplicate rate | 0.0000 | 0.0000 | 0.0000 |
| p50 latency | 505.1 ms | 336.8 ms | -168.3 ms |
| p95 latency | 663.8 ms | 427.1 ms | -236.6 ms |

| Holdout metric | A2 V2 | V3 | Delta |
|---|---:|---:|---:|
| Lexical hit@1 | 0.5333 | 0.8000 | +0.2667 |
| Lexical hit@5 | 0.7333 | 0.9333 | +0.2000 |
| MRR | 0.6222 | 0.8467 | +0.2244 |
| nDCG@5 | 0.9086 | 0.9172 | +0.0086 |
| Timestamp provenance coverage | 0.0000 | 1.0000 | +1.0000 |
| No-answer accuracy | 0.5000 | 1.0000 | +0.5000 |
| Duplicate rate | 0.0000 | 0.0000 | 0.0000 |

The one explicitly timestamp-labelled benchmark case scored timestamp accuracy `0.0` on both V2 and V3; this is disclosed as a limitation and was not mislabeled as a pass. Provenance coverage is separate telemetry and reached `1.0` on V3.

Promotion comparison: **PASSED — all nine fail-closed gates true.** The comparator recomputed aggregates from paired per-case rows rather than trusting report summaries.

Final reports:

- `benchmark-v2-a2-regate-2.json`
- `benchmark-v3-regate-3.json`
- `benchmark-comparison-regate-3.json`
- `golden-eval-regate-3.json`

## Tests, review, and static verification

- Full repository suite: **190 passed**, one unrelated dependency deprecation warning.
- Real demo integration: V3 ingestion, schema-2 completion attestation, encryption, licence generation, and encrypted open all passed without subprocess mocks.
- Focused blocker regression suites: passed.
- Python compile checks: passed.
- `git diff --check`: passed.
- Changed-file secret-value scan: passed across 40 files.
- The first exact-tree review failed closed and exposed licence-integrity, build-binding, buyer-runtime, research-bundle, deeplink-provenance, and audit-date defects; each now has a focused regression test plus real runtime verification.
- The second exact-tree review failed closed on live-corpus binding, result-ref timestamp propagation, prospective bundle caps, the real demo pipeline, delivery-time licence binding, and stale ZIP checksum evidence; all six were repaired and regated before this audit revision.
- The third exact-tree review failed closed on two remaining TOCTOU windows: source mutation during encryption and vault mutation between licence verification and delivery copy. Publication now rechecks the live corpus after encryption immediately before its first atomic write; delivery packages only a hash-verified private vault snapshot and exact verified licence bytes. Both races have focused regressions.
- Final independent review must still verify the exact staged tree immediately before commit. Its result belongs in commit/PR metadata rather than being self-asserted in this audit.

## Rollback rehearsal

- Production V2 matches the protected pre-release fingerprint.
- Physical rollback `D:\PlugICT\releases\v2-20260716-110921\ict-vault.kevin` is byte-identical to production V2.
- No V3 build, package, benchmark, or test operation replaced, renamed, or modified production V2.

## Remaining owner-operated launch checks

These do not block the feature-branch commit, but remain mandatory before public production promotion:

- fresh Windows profile/VM installation from the final buyer ZIP;
- one real MCP-client connection from the packaged ZIP;
- manual Stripe purchase/fulfilment rehearsal;
- explicit owner approval before replacing production V2.
