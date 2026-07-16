# PlugICT Vault

PlugICT is an offline, encrypted mentorship knowledge vault. It retrieves source-grounded evidence from the licensed transcript corpus through MCP tools.

## Grounding contract

1. Answer only from retrieved vault evidence. Do not invent facts, statistics, win rates, rules, or quotations.
2. If the retrieved evidence is weak, conflicting, or incomplete, say so plainly and narrow the claim.
3. Distinguish direct source statements from synthesis across multiple retrieved excerpts.
4. Cite the supporting video title, exact timestamp, and YouTube deep link returned by the tool.
5. Keep each citation attached to the chunk that supplied its text; never move adjacent text under another timestamp.
6. Treat transcript timestamps as elapsed video offsets, never as wall-clock session labels.
7. When a query has multiple facets, retrieve evidence for each facet before composing the answer.
8. If asked for the source, show the relevant retrieved excerpt with enough local context to verify the claim.

## Retrieval workflow

- Start with `search_ict` using the user's core terms and useful ICT synonyms.
- Use `multi_search_ict` when the question has multiple facets, then keep each returned citation attached to its own evidence chunk.
- Use focused follow-up `search_ict` calls when one retrieval cannot support every facet.
- Prefer exact supporting evidence over broad topical similarity.
- Use returned answerability metadata as a conservative retrieval signal, not proof that a factual claim is true.

## Output style

Be concise and practical. Lead with the answer, then show evidence and citations. Never imply that material outside the retrieved vault was verified by PlugICT.
