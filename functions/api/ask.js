// PlugICT Chatbar — POST /api/ask
// Auth → credits → KV cache → hybrid retrieval (Vectorize + FTS5) →
// R2 context → buffered DeepSeek validation → SSE answer with server-owned
// exact transcript excerpts, timestamps, and YouTube deeplinks.
//
// Requires env (Cloudflare Pages secrets/vars):
//   DEEPSEEK_API_KEY (secret), optional DEEPSEEK_URL / DEEPSEEK_MODEL
//   overrides (OpenAI-compatible gateway; defaults: DeepSeek direct API),
//   ALLOWED_ORIGINS (var), SUPABASE_URL (public var; JWTs verified via public JWKS)
// Bindings: CHAT_DB (D1 plugict-chat-db), VECTORIZE (plugict-vault-index),
//           VAULT_R2 (plugict-vault), CACHE (KV plugict-chat-cache)

import { sha256Hex, verifySupabaseJwt } from '../../cloudflare/lib/auth.js';
import { errorResponse, corsHeaders } from '../../cloudflare/lib/http.js';
import {
  dayBucket,
  tsToSeconds,
  deeplink,
  buildFts5Query,
  extractTimedSegments,
  createDeepSeekSseDecoder,
  sseDeltaEvent,
  sseFinalEvent,
} from '../../cloudflare/lib/chat-utils.js';

// Model endpoint is deployment-overridable (e.g. OpenCode Go gateway at
// https://opencode.ai/zen/go/v1/chat/completions, which hosts deepseek-v4-flash).
// Defaults stay pinned to DeepSeek's own API; override via env vars
// DEEPSEEK_URL / DEEPSEEK_MODEL. The resolved model participates in cache
// identity, so switching endpoints/models never reuses stale answers.
const DEFAULT_MODEL = 'deepseek-v4-flash';
const DEFAULT_DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions';
const TEMPERATURE = 0.3;
const PROMPT_VERSION = 'grounded-json-v1';
const RETRIEVAL_VERSION = 'hybrid-vector-fts-exact-r2-v2';
// Output-contract enforcement: the model may not place direct quotes,
// timestamps, source links, or markdown fences inside `answer`. The server
// attaches exact source excerpts itself, so any such content is treated as
// fabrication and fails closed.
const FORBIDDEN_ANSWER_CONTENT = [
  /["“”]/,
  /\b\d{1,3}:\d{2}(?::\d{2})?\b/,
  /https?:\/\/|www\./i,
  /```/,
];
const CACHE_ENVELOPE_VERSION = 1;
const GROUNDING_MARKER = 'exact-r2';
const CORPUS_VERSION = 'chunks-0e405ddd9318345f6c507f540cfb90c2c88d5c540cdf5292b4c871ccbb7e2eba:transcripts-12bc027354b9100b3d9e54abf15b9920bc8e32a1e9e024cec501d8c62ce007a7';

const MAX_INPUT = 200;
// Defaults; overridable per deployment via env vars.
const DEFAULT_TOP_K = 6;
const DEFAULT_MAX_CONTEXT_CHARS = 16000;
// Calibrated on the immutable 21,376-vector export: representative ICT top-4
// scores were >=0.7416 while sampled off-topic maxima were <=0.6011.
const DEFAULT_MIN_VECTOR_SCORE = 0.65;

const LIMITS = {
  free: { questions: 5, dailyReset: false, maxOutputChars: 4000, maxTokens: 1500 },
  premium: { questions: 100, dailyReset: true, maxOutputChars: 4000, maxTokens: 1500 },
  pro: { questions: 500, dailyReset: true, maxOutputChars: 8000, maxTokens: 2500 },
};
const CACHE_TTL = 86400;          // 24h KV cache for repeat questions

// ── Session
function requestAccessToken(request) {
  const authorization = request.headers.get('Authorization');
  if (authorization !== null) {
    const match = /^Bearer\s+(.+)$/i.exec(authorization.trim());
    return { provided: true, token: match?.[1]?.trim() || '' };
  }

  return { provided: false, token: '' };
}

async function resolveUser(request, env) {
  const credentials = requestAccessToken(request);
  if (!credentials.provided) return { tokenProvided: false, user: null };
  if (!credentials.token || !env.SUPABASE_URL) return { tokenProvided: true, user: null };
  // Fail closed: bad ES256 signature, expired, or wrong issuer -> invalid session.
  const user = await verifySupabaseJwt(credentials.token, env.SUPABASE_URL);
  return { tokenProvided: true, user };
}

async function getPlan(env, userId) {
  const row = await env.CHAT_DB.prepare(
    'SELECT plan FROM user_plans WHERE user_id = ?1'
  ).bind(userId).first();
  return Object.hasOwn(LIMITS, row?.plan) ? row.plan : 'free';
}

function usagePeriod(policy, now = Date.now()) {
  return policy.dailyReset
    ? new Date(dayBucket(now) * 86400000).toISOString().slice(0, 10)
    : 'lifetime';
}

export async function reserveUsage(env, key, policy, now = Date.now()) {
  const scope = String(key.scope || (policy.dailyReset ? 'paid' : 'free'));
  const periodKey = usagePeriod(policy, now);
  const result = await env.CHAT_DB.prepare(
    `INSERT INTO chat_usage_scoped
       (user_id, entitlement_scope, period_key, questions_used, first_question_at, last_question_at)
     VALUES (?1, ?2, ?3, 1, ?4, ?4)
     ON CONFLICT(user_id, entitlement_scope, period_key) DO UPDATE SET
       questions_used = chat_usage_scoped.questions_used + 1,
       last_question_at = excluded.last_question_at
     WHERE chat_usage_scoped.questions_used < ?5`
  ).bind(key.userId, scope, periodKey, now, policy.questions).run();

  const changes = Number(result?.meta?.changes || 0);
  if (changes < 1) return { allowed: false, used: policy.questions, scope, periodKey };

  let used = policy.questions;
  try {
    const row = await env.CHAT_DB.prepare(
      `SELECT questions_used FROM chat_usage_scoped
        WHERE user_id = ?1 AND entitlement_scope = ?2 AND period_key = ?3`
    ).bind(key.userId, scope, periodKey).first();
    used = Math.max(1, Number(row?.questions_used) || 1);
  } catch (error) {
    console.error('usage readback error:', error?.message || error);
  }
  return { allowed: true, used, scope, periodKey };
}

export async function refundUsage(env, key, reservation) {
  await env.CHAT_DB.prepare(
    `UPDATE chat_usage_scoped
        SET questions_used = questions_used - 1,
            first_question_at = CASE WHEN questions_used <= 1 THEN NULL ELSE first_question_at END
      WHERE user_id = ?1 AND entitlement_scope = ?2 AND period_key = ?3
        AND questions_used > 0`
  ).bind(key.userId, reservation.scope, reservation.periodKey).run();
}

// Refund the exact reservation; if the ledger cannot be finalized, surface a
// 503 instead of silently leaving the credit consumed. Unresolved refunds are
// never suppressed.
async function refundOrError(request, env, key, reservation) {
  try {
    await refundUsage(env, key, reservation);
    return null;
  } catch (error) {
    console.error('usage refund failure:', error?.message || error);
    return errorResponse(
      request, env, 503,
      'Usage ledger could not be finalized. No credit was released — retry shortly.',
    );
  }
}

async function recordChatLog(env, { questionHash, plan, latencyMs, cacheHit }) {
  try {
    await env.CHAT_DB.prepare(
      `INSERT INTO chat_log (question_hash, plan, latency_ms, cache_hit, created_at)
       VALUES (?1, ?2, ?3, ?4, ?5)`,
    ).bind(questionHash, plan, latencyMs, cacheHit ? 1 : 0, Date.now()).run();
  } catch (error) {
    console.error('chat analytics write error:', error?.message || error);
  }
}

// A cached answer is only trusted when its envelope is complete and matches
// every response-affecting policy boundary of the CURRENT request. Anything
// else is stale, forged, or from an incompatible release — treat as a miss.
function isValidCacheEnvelope(entry, maxOutputChars, model) {
  if (!entry || typeof entry !== 'object') return false;
  if (entry.v !== CACHE_ENVELOPE_VERSION) return false;
  if (entry.corpus !== CORPUS_VERSION) return false;
  if (entry.model !== model) return false;
  if (entry.prompt !== PROMPT_VERSION) return false;
  if (entry.retrieval !== RETRIEVAL_VERSION) return false;
  if (entry.grounding !== GROUNDING_MARKER) return false;
  if (entry.maxOutputChars !== maxOutputChars) return false;
  if (typeof entry.answer !== 'string' || !entry.answer || entry.answer.length > maxOutputChars) return false;
  if (!Array.isArray(entry.sources) || entry.sources.length < 1 || entry.sources.length > 4) return false;
  return entry.sources.every((source) => (
    source && typeof source === 'object'
    && typeof source.evidence_id === 'string' && source.evidence_id
    && typeof source.video_id === 'string' && source.video_id
    && typeof source.quote === 'string' && source.quote
  ));
}

// ── Tool-calling: AI-driven retrieval ──────────────────────────────────
const MAX_TOOL_ROUNDS = 3;
const VAULT_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'search_vault',
      description: 'Search the ICT transcript vault for relevant content. Returns matching video excerpts with timestamps and evidence IDs.',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Search query using ICT terminology' },
        },
        required: ['query'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'expand_transcript',
      description: 'Load a specific time range from a video transcript for more context.',
      parameters: {
        type: 'object',
        properties: {
          video_id: { type: 'string', description: 'Video ID from a search result' },
          start_seconds: { type: 'number', description: 'Start time in seconds' },
          end_seconds: { type: 'number', description: 'End time in seconds' },
        },
        required: ['video_id', 'start_seconds', 'end_seconds'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_related_chunks',
      description: 'Find other chunks from the same video to explore related content.',
      parameters: {
        type: 'object',
        properties: {
          chunk_id: { type: 'string', description: 'Chunk ID from a search result' },
        },
        required: ['chunk_id'],
      },
    },
  },
];

// ── Retrieval: Vectorize first, FTS5 fallback ───────────────────────────
async function embedQuery(env, text) {
  if (env.AI) {
    const r = await env.AI.run('@cf/baai/bge-small-en-v1.5', { text: [text] });
    return r?.data?.[0] || null;
  }
  return null;
}

// Multi-query expansion: ask the AI to generate 2-3 concise search queries
// from a verbose/unclear user question. Each variant is embedded separately
// and searched, so the vault is explored from multiple angles.
async function expandQueries(env, question, dsUrl) {
  const body = {
    model: env.DEEPSEEK_MODEL || DEFAULT_MODEL,
    messages: [
      {
        role: 'system',
        content: `You are a search query optimizer for an ICT (Inner Circle Trader) trading education vault.
The user asked a question. Generate exactly 2 concise search queries that would find relevant ICT concepts in a transcript vault.
Return ONLY a JSON array of strings, nothing else. Example: ["silver bullet model ICT", "ICT silver bullet entry criteria"]`,
      },
      { role: 'user', content: question },
    ],
    max_tokens: 120,
    temperature: 0.1,
    stream: false,
  };
  try {
    const res = await fetch(dsUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
        'User-Agent': 'PlugICT-Chatbar/1.0',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return [question];
    const data = await res.json();
    const content = data?.choices?.[0]?.message?.content || '';
    // Normalize double-escaped JSON from gateway
    let cleaned = content.trim();
    try { JSON.parse(cleaned); } catch { cleaned = cleaned.replaceAll('\\"', '"'); }
    const queries = JSON.parse(cleaned);
    if (Array.isArray(queries) && queries.length >= 1 && queries.length <= 4) {
      return [question, ...queries.filter((q) => typeof q === 'string' && q !== question)];
    }
  } catch (e) {
    console.error('query expansion error:', e.message);
  }
  return [question];
}

// Multi-round tool-calling loop: the AI drives retrieval.
// Returns { answer, evidenceById } on success, or null on failure.
async function toolCallLoop(env, question, dsUrl, model, policy, topK, minScore) {
  const evidenceById = new Map();
  const transcriptCache = new Map();
  const messages = [
    {
      role: 'system',
      content: buildSystemPrompt(policy.maxOutputChars)
        + '\n\nYou have access to tools to search the ICT transcript vault. '
        + 'Use search_vault first to find relevant evidence, then expand_transcript or get_related_chunks if you need more context. '
        + 'After gathering evidence, answer using the exact JSON format specified in the system prompt.',
    },
    { role: 'user', content: question },
  ];

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    let data;
    try {
      const res = await fetch(dsUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
          'User-Agent': 'PlugICT-Chatbar/1.0',
        },
        body: JSON.stringify({
          model, messages, tools: VAULT_TOOLS,
          max_tokens: policy.maxTokens, temperature: TEMPERATURE, stream: false,
        }),
      });
      if (!res.ok) { console.error('tool-call http', res.status); return null; }
      data = await res.json();
    } catch (e) {
      console.error('tool-call error:', e.message);
      return null;
    }

    const choice = data?.choices?.[0];
    const message = choice?.message;
    if (!message) return null;

    // No tool calls → final answer
    if (!message.tool_calls?.length) {
      return { answer: message.content || '', evidenceById };
    }

    // Process tool calls
    messages.push(message);
    for (const tc of message.tool_calls) {
      const result = await executeTool(env, tc, evidenceById, topK, minScore);
      messages.push({ role: 'tool', tool_call_id: tc.id, content: result });
    }
  }
  return null;
}

async function retrieve(env, question, embeddings, topK, minScore) {
  const matches = [];
  const seen = new Set();
  for (const embedding of embeddings) {
    if (!embedding) continue;
    try {
      const res = await env.VECTORIZE.query(embedding, {
        topK,
        returnMetadata: 'indexed',
        filter: { contentType: 'transcript_chunk' },
      });
      for (const m of res?.matches || []) {
        if (!Number.isFinite(Number(m.score)) || Number(m.score) < minScore) continue;
        if (seen.has(m.id)) continue;
        seen.add(m.id);
        matches.push({
          chunkId: m.id,
          videoId: m.metadata?.video_id,
          playlist: m.metadata?.playlist,
          title: m.metadata?.title,
          startTs: m.metadata?.start_ts,
          endTs: m.metadata?.end_ts,
          startSeconds: m.metadata?.start_seconds,
          endSeconds: m.metadata?.end_seconds,
          score: m.score,
        });
      }
    } catch (e) {
      console.error('vectorize error:', e.message);
    }
  }

  if (matches.length === 0) {
    // FTS5 keyword fallback (BM25)
    const q = buildFts5Query(question);
    if (q) {
      try {
        const res = await env.CHAT_DB.prepare(
          `SELECT chunk_id, title, video_id, playlist, start_ts, end_ts,
                  start_seconds, end_seconds, content
             FROM vault_fts WHERE vault_fts MATCH ?1 ORDER BY rank LIMIT ?2`
        ).bind(q, topK).all();
        for (const r of res?.results || []) {
          matches.push({
            chunkId: r.chunk_id,
            videoId: r.video_id,
            playlist: r.playlist,
            title: r.title,
            startTs: r.start_ts,
            endTs: r.end_ts,
            startSeconds: r.start_seconds,
            endSeconds: r.end_seconds,
            text: r.content,
            score: 1,
          });
        }
      } catch (e) {
        console.error('fts5 error:', e.message);
      }
    }
  }
  // Sort by score descending, keep top-K overall
  matches.sort((a, b) => b.score - a.score);
  return matches.slice(0, topK);
}

// Execute a tool call from the AI and return the result as a string.
async function executeTool(env, toolCall, evidenceById, topK, minScore) {
  const name = toolCall.function?.name;
  let args;
  try { args = JSON.parse(toolCall.function?.arguments || '{}'); } catch { args = {}; }

  if (name === 'search_vault') {
    const query = String(args.query || '').slice(0, 200);
    if (!query) return JSON.stringify({ error: 'Empty query' });
    const emb = await embedQuery(env, query);
    const matches = await retrieve(env, query, emb ? [emb] : [], topK, minScore);
    if (!matches.length) return JSON.stringify({ results: [], message: 'No matches found' });
    const results = [];
    for (const m of matches.slice(0, 4)) {
      const segments = await loadTimestampedEvidence(env, m);
      const id = `E${evidenceById.size + 1}`;
      const url = deeplink(m.videoId, m.startSeconds);
      evidenceById.set(id, {
        evidence_id: id, video_id: m.videoId, playlist: m.playlist || 'Other / Misc',
        title: m.title || m.videoId, timestamp: m.startTs, seconds: m.startSeconds,
        url, quote: segments.map(s => s.text).join(' '),
      });
      results.push({ evidence_id: id, video_id: m.videoId, title: m.title, timestamp: m.startTs, score: m.score, excerpt: segments.map(s => `[${s.timestamp}] ${s.text}`).join('\n') });
    }
    return JSON.stringify({ results });
  }

  if (name === 'expand_transcript') {
    const vid = String(args.video_id || '');
    const start = Number(args.start_seconds) || 0;
    const end = Number(args.end_seconds) || start + 300;
    const row = await env.CHAT_DB.prepare('SELECT r2_key, source_file FROM vault_chunks WHERE video_id = ?1 LIMIT 1').bind(vid).first();
    if (!row) return JSON.stringify({ error: `Video ${vid} not found` });
    const obj = await env.VAULT_R2.get(row.r2_key);
    if (!obj) return JSON.stringify({ error: 'Transcript not in R2' });
    const text = await obj.text();
    const segments = extractTimedSegments(text, start, end, 50);
    return JSON.stringify({ video_id: vid, segments: segments.map(s => `[${s.timestamp}] ${s.text}`) });
  }

  if (name === 'get_related_chunks') {
    const chunkId = String(args.chunk_id || '');
    const chunk = await env.CHAT_DB.prepare('SELECT video_id, playlist FROM vault_chunks WHERE id = ?1').bind(chunkId).first();
    if (!chunk) return JSON.stringify({ error: 'Chunk not found' });
    const related = await env.CHAT_DB.prepare(
      'SELECT id, title, start_ts, end_ts, start_seconds, end_seconds FROM vault_chunks WHERE video_id = ?1 AND id != ?2 ORDER BY chunk_idx LIMIT 5'
    ).bind(chunk.video_id, chunkId).all();
    return JSON.stringify({ video_id: chunk.video_id, playlist: chunk.playlist, related: related.results || [] });
  }

  return JSON.stringify({ error: `Unknown tool: ${name}` });
}

async function loadTimestampedEvidence(env, match, transcriptCache) {
  if (!match.chunkId || !match.videoId) return [];
  if (!env.VAULT_R2?.get) throw new Error('VAULT_R2 binding is unavailable');

  const row = await env.CHAT_DB.prepare(
    'SELECT r2_key, source_file FROM vault_chunks WHERE id = ?1'
  ).bind(match.chunkId).first();
  const keyMatch = /^transcripts\/by-source\/([0-9a-f]{64})\.md$/.exec(String(row?.r2_key || ''));
  if (!keyMatch || !row?.source_file) {
    throw new Error(`Content-addressed R2 provenance missing for chunk ${match.chunkId}`);
  }

  const transcriptIdentity = `${row.r2_key}\0${row.source_file}`;
  let transcriptPromise = transcriptCache.get(transcriptIdentity);
  if (!transcriptPromise) {
    transcriptPromise = Promise.resolve(env.VAULT_R2.get(row.r2_key)).then(async (object) => {
      if (!object?.text) throw new Error(`R2 transcript missing: ${row.r2_key}`);
      const text = await object.text();
      const actualHash = await sha256Hex(`${row.source_file}\0${text}`);
      if (actualHash !== keyMatch[1]) {
        throw new Error(`R2 transcript integrity mismatch: ${row.r2_key}`);
      }
      return text;
    });
    transcriptCache.set(transcriptIdentity, transcriptPromise);
  }

  const transcript = await transcriptPromise;
  const start = match.startSeconds != null ? Number(match.startSeconds) : tsToSeconds(match.startTs);
  const end = match.endSeconds != null ? Number(match.endSeconds) : tsToSeconds(match.endTs);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start) return [];
  const segments = extractTimedSegments(transcript, start, end);
  const monotonic = segments.every((segment, index) => (
    index === 0 || segment.seconds >= segments[index - 1].seconds
  ));
  if (!segments.length
    || !monotonic
    || segments[0].seconds !== start
    || segments.at(-1).seconds !== end) return [];
  return segments;
}

// ── System prompt — the SELLING POINT instructions ──────────────────────
function buildSystemPrompt(maxOutputChars) {
  return `You are PlugICT's AI assistant — an ICT (Inner Circle Trader) knowledge guide built from ICT's own video vault.

OUTPUT CONTRACT — CRITICAL:
1. Return one valid JSON object only, with exactly this shape: {"answer":"...","evidence_ids":["E1"]}.
2. Explain the concept in 2-4 short beginner-friendly paragraphs in answer.
3. Select 1-4 evidence IDs that directly support the answer. IDs must come from the supplied vault context.
4. Do not place direct quotes, timestamps, source links, markdown fences, or extra keys inside answer. The server attaches exact source excerpts itself.
5. answer must stay under ${maxOutputChars} characters.
6. NEVER invent evidence IDs. Do not answer from memory. If no supplied evidence directly answers the question, return {"answer":"","evidence_ids":[]}.
7. If the question is not about ICT/trading concepts, return {"answer":"","evidence_ids":[]}.`;
}

function parseGroundedCompletion(raw, evidenceById, maxOutputChars) {
  let parsed;
  const text = String(raw || '').trim();
  try {
    parsed = JSON.parse(text);
  } catch {
    // Some OpenAI-compatible gateways (e.g. OpenCode Go serving
    // deepseek-v4-flash) double-escape JSON inside streamed deltas:
    // {\"answer\":\"...\"} instead of {"answer":"..."}. Normalize the
    // escapes before declaring the completion invalid.
    try {
      parsed = JSON.parse(text.replaceAll('\\"', '"'));
    } catch {
      return null;
    }
  }
  const answer = typeof parsed?.answer === 'string' ? parsed.answer.trim() : '';
  const ids = Array.isArray(parsed?.evidence_ids) ? [...new Set(parsed.evidence_ids)] : [];
  if (!answer || answer.length > maxOutputChars || ids.length < 1 || ids.length > 4) return null;
  if (!ids.every((id) => typeof id === 'string' && evidenceById.has(id))) return null;
  // The output contract forbids direct quotes, timestamps, source links and
  // markdown fences inside answer — the server attaches exact source excerpts
  // itself. A completion that violates the contract may be fabricating
  // content, so it fails closed exactly like an invalid evidence ID.
  if (FORBIDDEN_ANSWER_CONTENT.some((pattern) => pattern.test(answer))) return null;
  return { answer, sources: ids.map((id) => evidenceById.get(id)) };
}

// ── Main handlers ───────────────────────────────────────────────────────
export async function onRequestGet({ request, env }) {
  const authState = await resolveUser(request, env);
  if (!authState.tokenProvided || !authState.user?.userId) {
    return errorResponse(request, env, 401, 'Invalid or expired session.');
  }

  const plan = await getPlan(env, authState.user.userId);
  const policy = LIMITS[plan] || LIMITS.free;
  let used = 0;
  try {
    const row = await env.CHAT_DB.prepare(
      `SELECT questions_used FROM chat_usage_scoped
        WHERE user_id = ?1 AND entitlement_scope = ?2 AND period_key = ?3`
    ).bind(authState.user.userId, plan, usagePeriod(policy)).first();
    used = Math.max(0, Number(row?.questions_used) || 0);
  } catch (error) {
    console.error('usage status error:', error?.message || error);
    return errorResponse(request, env, 503, 'Usage service unavailable — try again in a moment.');
  }

  const headers = corsHeaders(request, env);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify({
    plan,
    remaining: Math.max(0, policy.questions - used),
    limit: policy.questions,
    dailyReset: policy.dailyReset,
  }), { status: 200, headers });
}

export async function onRequestPost({ request, env, waitUntil }) {
  const startedAt = Date.now();
  const cors = corsHeaders(request, env);

  // 1. Auth
  const authState = await resolveUser(request, env);
  if (!authState.tokenProvided || !authState.user?.userId) {
    return errorResponse(request, env, 401, 'Invalid or expired session.');
  }
  const userId = authState.user.userId;

  // 2. Validate input before reserving a credit
  let body;
  try { body = await request.json(); } catch { return errorResponse(request, env, 400, 'Invalid JSON body'); }
  const question = String(body?.question || '').trim();
  if (!question) return errorResponse(request, env, 400, 'Missing question');
  if (question.length > MAX_INPUT) return errorResponse(request, env, 400, `Question too long (max ${MAX_INPUT} chars)`);

  // 3. Atomically reserve one entitlement credit before cache/retrieval/upstream cost.
  const plan = await getPlan(env, userId);
  const policy = LIMITS[plan] || LIMITS.free;
  const key = { userId, scope: plan };
  let reservation;
  try {
    reservation = await reserveUsage(env, key, policy);
  } catch (error) {
    console.error('usage reservation error:', error?.message || error);
    return errorResponse(request, env, 503, 'Usage service unavailable — try again in a moment.');
  }
  if (!reservation.allowed) {
    const message = policy.dailyReset
      ? `Daily limit reached (${policy.questions} questions per day).`
      : `Free question allowance used (${policy.questions} questions per account).`;
    const headers = cors;
    headers.set('Content-Type', 'application/json; charset=utf-8');
    return new Response(JSON.stringify({
      error: message,
      plan,
      remaining: 0,
      limit: policy.questions,
      dailyReset: policy.dailyReset,
    }), { status: 429, headers });
  }
  const remaining = Math.max(0, policy.questions - reservation.used);

  // Model endpoint resolved per deployment: DEEPSEEK_URL / DEEPSEEK_MODEL
  // overrides (e.g. OpenCode Go gateway); defaults stay on DeepSeek direct.
  const model = env.DEEPSEEK_MODEL || DEFAULT_MODEL;
  const dsUrl = env.DEEPSEEK_URL || DEFAULT_DEEPSEEK_URL;
  // Search knobs: overridable per deployment via env vars.
  const topK = Number(env.TOP_K) || DEFAULT_TOP_K;
  const minScore = Number(env.MIN_VECTOR_SCORE) || DEFAULT_MIN_VECTOR_SCORE;
  const maxContextChars = Number(env.MAX_CONTEXT_CHARS) || DEFAULT_MAX_CONTEXT_CHARS;
  const multiquery = env.MULTIQUERY !== 'false'; // default ON

  // 4. KV cache (repeat questions instant, no LLM cost)
  const qHash = await sha256Hex(question);
  const cacheScope = [
    `plan:${plan}`,
    `output:${policy.maxOutputChars}`,
    `tokens:${policy.maxTokens}`,
    `model:${model}`,
    `temperature:${TEMPERATURE}`,
    `prompt:${PROMPT_VERSION}`,
    `retrieval:${RETRIEVAL_VERSION}`,
    `top-k:${topK}`,
    `min-vector-score:${minScore}`,
    `context-chars:${maxContextChars}`,
    `corpus:${CORPUS_VERSION}`,
  ].join('|');
  const cacheKey = `qa:${await sha256Hex(`${cacheScope}\n${question}`)}`;
  let cached = null;
  try {
    cached = await env.CACHE?.get(cacheKey, 'json');
  } catch (error) {
    console.error('chat cache read error:', error?.message || error);
  }
  if (cached && isValidCacheEnvelope(cached, policy.maxOutputChars, model)) {
    const headers = cors;
    headers.set('Content-Type', 'application/json; charset=utf-8');
    headers.set('X-Cache', 'HIT');
    const logWrite = recordChatLog(env, {
      questionHash: qHash,
      plan,
      latencyMs: Date.now() - startedAt,
      cacheHit: true,
    });
    if (typeof waitUntil === 'function') waitUntil(logWrite);
    else await logWrite;
    return new Response(JSON.stringify({
      ...cached,
      remaining,
      plan,
      limit: policy.questions,
      dailyReset: policy.dailyReset,
    }), { status: 200, headers });
  }
  if (cached) {
    // A stale or forged envelope must not be served as a verified answer.
    // Drop it and treat this request as a cache miss.
    console.error('chat cache envelope rejected; deleting', cacheKey);
    Promise.resolve(env.CACHE?.delete(cacheKey)).catch((error) => {
      console.error('chat cache delete error:', error?.message || error);
    });
  }

  // 5. Retrieval: try tool-calling first (AI-driven), fall back to single-shot
  let rawCompletion = '';
  let evidenceById = new Map();

  if (multiquery) {
    try {
      const result = await toolCallLoop(env, question, dsUrl, model, policy, topK, minScore);
      if (result?.answer) {
        rawCompletion = result.answer;
        evidenceById = result.evidenceById;
      }
    } catch (e) {
      console.error('tool-call loop failed, falling back:', e.message);
    }
  }

  // Fallback: single-shot retrieval (existing path)
  if (!rawCompletion || evidenceById.size === 0) {
    try {
      let embedding = null;
      try {
        embedding = await embedQuery(env, question);
      } catch (error) {
        console.error('embedding error, falling back to FTS5:', error?.message || error);
      }
      const matches = await retrieve(env, question, embedding ? [embedding] : [], topK, minScore);
      if (matches.length) {
        const parts = [];
        const transcriptCache = new Map();
        let contextLength = 0;
        for (const m of matches) {
          const segments = await loadTimestampedEvidence(env, m, transcriptCache);
          if (!segments.length) continue;
          const lines = [];
          const candidates = [];
          for (const segment of segments) {
            const id = `E${evidenceById.size + candidates.length + 1}`;
            const url = deeplink(m.videoId, segment.seconds);
            lines.push(`[${id} | ${segment.timestamp} | ${url}] ${segment.text}`);
            candidates.push([id, {
              evidence_id: id,
              video_id: m.videoId,
              playlist: m.playlist || 'Other / Misc',
              title: m.title || m.videoId,
              timestamp: segment.timestamp,
              seconds: segment.seconds,
              url,
              quote: segment.text,
            }]);
          }
          const part = `[SOURCE video=${m.videoId} playlist=${m.playlist || '?'} range=${m.startTs || '0:00'}-${m.endTs || '?'}]\n${lines.join('\n')}`;
          if (contextLength + part.length + 7 > maxContextChars) continue;
          for (const [id, source] of candidates) evidenceById.set(id, source);
          parts.push(part);
          contextLength += part.length + 7;
        }
        const context = parts.join('\n\n---\n\n');
        if (context && evidenceById.size > 0) {
          // Single-shot streaming call
          let dsRes;
          try {
            dsRes = await fetch(dsUrl, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
                'User-Agent': 'PlugICT-Chatbar/1.0',
              },
              body: JSON.stringify({
                model,
                messages: [
                  { role: 'system', content: buildSystemPrompt(policy.maxOutputChars) },
                  { role: 'user', content: `${context}\n\nQUESTION: ${question}` },
                ],
                max_tokens: policy.maxTokens,
                temperature: TEMPERATURE,
                stream: true,
              }),
            });
          } catch (e) {
            console.error('deepseek connect error:', e.message);
            const refundError = await refundOrError(request, env, key, reservation);
            if (refundError) return refundError;
            return errorResponse(request, env, 502, 'AI service unavailable — try again in a moment.');
          }
          if (!dsRes.ok || !dsRes.body) {
            const errText = await dsRes.text().catch(() => '');
            console.error('deepseek http', dsRes.status, errText.slice(0, 300));
            const refundError = await refundOrError(request, env, key, reservation);
            if (refundError) return refundError;
            return errorResponse(request, env, 502, 'AI service unavailable — try again in a moment.');
          }
          const reader = dsRes.body.getReader();
          const upstream = createDeepSeekSseDecoder();
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              rawCompletion += upstream.push(value);
            }
            rawCompletion += upstream.flush();
          } catch (e) {
            console.error('stream error:', e.message);
            const refundError = await refundOrError(request, env, key, reservation);
            if (refundError) return refundError;
            return errorResponse(request, env, 502, 'AI stream interrupted — please retry.');
          } finally {
            try { await reader.cancel(); } catch { /* ignore */ }
          }
          if (!upstream.doneSeen() || upstream.finishReason() !== 'stop' || upstream.malformed()) {
            const refundError = await refundOrError(request, env, key, reservation);
            if (refundError) return refundError;
            return errorResponse(request, env, 422, 'AI did not return a complete verified answer. Try rephrasing your question.');
          }
        }
      }
    } catch (error) {
      console.error('retrieval error:', error?.message || error);
      const refundError = await refundOrError(request, env, key, reservation);
      if (refundError) return refundError;
      return errorResponse(request, env, 502, 'Knowledge search unavailable — try again in a moment.');
    }
  }

  if (!rawCompletion || evidenceById.size === 0) {
    const refundError = await refundOrError(request, env, key, reservation);
    if (refundError) return refundError;
    return errorResponse(request, env, 422, 'No matching timestamped vault evidence found. Try rephrasing your question.');
  }

  // 6. Validate and stream
  const grounded = parseGroundedCompletion(rawCompletion, evidenceById, policy.maxOutputChars);
  if (!grounded) {
    const refundError = await refundOrError(request, env, key, reservation);
    if (refundError) return refundError;
    return errorResponse(request, env, 422, 'Answer could not be tied to verified source evidence. Try rephrasing your question.');
  }
  const { answer, sources } = grounded;

  if (answer.length > 40 && env.CACHE?.put) {
    const cacheWrite = Promise.resolve(env.CACHE.put(cacheKey, JSON.stringify({
      v: CACHE_ENVELOPE_VERSION,
      corpus: CORPUS_VERSION,
      model,
      prompt: PROMPT_VERSION,
      retrieval: RETRIEVAL_VERSION,
      maxOutputChars: policy.maxOutputChars,
      grounding: 'exact-r2',
      answer,
      sources,
      remaining,
      plan,
      limit: policy.questions,
      dailyReset: policy.dailyReset,
    }), { expirationTtl: CACHE_TTL })).catch((error) => {
      console.error('chat cache write error:', error?.message || error);
    });
    if (typeof waitUntil === 'function') {
      try { waitUntil(cacheWrite); } catch { await cacheWrite; }
    } else {
      await cacheWrite;
    }
  }

  const logWrite = recordChatLog(env, {
    questionHash: qHash,
    plan,
    latencyMs: Date.now() - startedAt,
    cacheHit: false,
  });
  if (typeof waitUntil === 'function') {
    try { waitUntil(logWrite); } catch { await logWrite; }
  } else {
    await logWrite;
  }

  const headers = cors;
  headers.set('Content-Type', 'text/event-stream');
  headers.set('Cache-Control', 'no-store');
  headers.set('X-Accel-Buffering', 'no');
  return new Response(
    sseDeltaEvent(answer) + sseFinalEvent(sources, remaining, plan, policy.questions, policy.dailyReset),
    { headers },
  );
}

// CORS preflight
export function onRequestOptions({ request, env }) {
  const headers = corsHeaders(request, env);
  headers.set('Content-Length', '0');
  return new Response(null, { status: 204, headers });
}
