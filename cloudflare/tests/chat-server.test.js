import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const utilsUrl = new URL('../lib/chat-utils.js', import.meta.url);
const askUrl = new URL('../../functions/api/ask.js', import.meta.url);
const wranglerUrl = new URL('../../wrangler.toml', import.meta.url);
const schemaUrl = new URL('../chat-db-schema.sql', import.meta.url);
const TEST_SUPABASE_URL = 'https://test-project.supabase.co';
const TEST_KID = 'chat-server-test-key';
const TEST_USER_ID = 'user-123';
const encoder = new TextEncoder();

const b64u = (bytes) => Buffer.from(bytes)
  .toString('base64')
  .replace(/\+/g, '-')
  .replace(/\//g, '_')
  .replace(/=+$/, '');

const testKeyPair = await crypto.subtle.generateKey(
  { name: 'ECDSA', namedCurve: 'P-256' },
  true,
  ['sign', 'verify'],
);
const testPublicJwk = {
  ...(await crypto.subtle.exportKey('jwk', testKeyPair.publicKey)),
  alg: 'ES256',
  kid: TEST_KID,
  use: 'sig',
  key_ops: ['verify'],
};

async function signedAccessToken() {
  const header = b64u(encoder.encode(JSON.stringify({ alg: 'ES256', typ: 'JWT', kid: TEST_KID })));
  const payload = b64u(encoder.encode(JSON.stringify({
    sub: TEST_USER_ID,
    email: 'buyer@example.com',
    aud: 'authenticated',
    role: 'authenticated',
    exp: Math.floor(Date.now() / 1000) + 3600,
    iss: `${TEST_SUPABASE_URL}/auth/v1`,
  })));
  const input = `${header}.${payload}`;
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' },
    testKeyPair.privateKey,
    encoder.encode(input),
  );
  return `${input}.${b64u(new Uint8Array(signature))}`;
}

function installAuthenticatedFetch(t, downstream = async () => {
  throw new Error('unexpected downstream fetch');
}) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (url, options) => {
    if (String(url) === `${TEST_SUPABASE_URL}/auth/v1/.well-known/jwks.json`) {
      return new Response(JSON.stringify({ keys: [testPublicJwk] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return downstream(url, options);
  };
}

async function authenticatedRequest(question, extraHeaders = {}) {
  return new Request('http://localhost:8788/api/ask', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${await signedAccessToken()}`,
      'Content-Type': 'application/json',
      Origin: 'http://localhost:8788',
      ...extraHeaders,
    },
    body: JSON.stringify({ question }),
  });
}

const MATCH = {
  chunk_id: 'chunk-1',
  video_id: 'video123',
  playlist: 'Core Content',
  title: 'Liquidity lesson',
  start_ts: '1:30',
  end_ts: '1:41',
  start_seconds: 90,
  end_seconds: 101,
};
const TIMED_TRANSCRIPT = [
  '1:30 Liquidity rests above old highs and below old lows.',
  '',
  '1:41 Those levels can act as a draw on price.',
  '',
  '2:01 Outside the selected chunk.',
].join('\n');
const TEST_SOURCE_FILE = 'fixtures/video123-source.md';

async function contentAddressedR2Key(sourceFile, content) {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    encoder.encode(`${sourceFile}\0${content}`),
  );
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `transcripts/by-source/${hex}.md`;
}

const TEST_R2_KEY = await contentAddressedR2Key(TEST_SOURCE_FILE, TIMED_TRANSCRIPT);

test('server prompt fails closed when vault evidence is unavailable', () => {
  const source = readFileSync(askUrl, 'utf8');
  assert.doesNotMatch(source, /answer from ICT methodology/i);
  assert.match(source, /do not answer from memory/i);
});

test('Workers AI query embedding is bound for Vectorize retrieval', () => {
  const source = readFileSync(askUrl, 'utf8');
  const config = readFileSync(wranglerUrl, 'utf8');
  assert.match(source, /env\.AI\.run\('@cf\/baai\/bge-small-en-v1\.5'/);
  assert.match(config, /\[ai\]\s+binding\s*=\s*"AI"/);
});

function makeDb({
  reservationChanges = 1,
  questionsUsed = 1,
  plan = null,
  ftsResults = [],
  r2Key = TEST_R2_KEY,
  sourceFile = TEST_SOURCE_FILE,
  r2Keys = null,
  r2Rows = null,
} = {}) {
  const runs = [];
  return {
    runs,
    prepare(sql) {
      return {
        bind(...params) {
          return {
            async first() {
              if (sql.includes('SELECT plan FROM user_plans')) return plan ? { plan } : null;
              if (sql.includes('SELECT r2_key, source_file FROM vault_chunks')) {
                const selected = r2Rows?.[params[0]];
                if (selected) return selected;
                const selectedKey = r2Keys?.[params[0]] ?? r2Key;
                return selectedKey ? { r2_key: selectedKey, source_file: sourceFile } : null;
              }
              if (sql.includes('SELECT questions_used, first_question_at')) return null;
              if (sql.includes('SELECT questions_used')) return { questions_used: questionsUsed };
              return null;
            },
            async all() {
              return { results: sql.includes('FROM vault_fts') ? ftsResults : [] };
            },
            async run() {
              runs.push({ sql, params });
              return {
                success: true,
                meta: { changes: reservationChanges, changed_db: reservationChanges > 0 },
              };
            },
          };
        },
      };
    },
  };
}

function makeEnv(db, overrides = {}) {
  return {
    ALLOWED_ORIGINS: 'http://localhost:8788',
    SUPABASE_URL: TEST_SUPABASE_URL,
    DEEPSEEK_API_KEY: 'test-only-key',
    MULTIQUERY: 'false', // Tests verify single-shot path; tool-calling has its own tests
    TOP_K: '4', // Preserve original test thresholds
    MIN_VECTOR_SCORE: '0.68',
    MAX_CONTEXT_CHARS: '12000',
    CHAT_DB: db,
    VAULT_R2: {
      async get(key) {
        assert.equal(key, TEST_R2_KEY);
        return { async text() { return TIMED_TRANSCRIPT; } };
      },
    },
    CACHE: { async get() { return null; } },
    ...overrides,
  };
}

function streamFromText(text, splitPoints = []) {
  const bytes = new TextEncoder().encode(text);
  const points = [...splitPoints, bytes.length]
    .filter((point, index, all) => point > 0 && point <= bytes.length && point > (all[index - 1] || 0));
  return new ReadableStream({
    start(controller) {
      let offset = 0;
      for (const point of points) {
        controller.enqueue(bytes.slice(offset, point));
        offset = point;
      }
      controller.close();
    },
  });
}

test('FTS5 fallback sanitizes punctuation and removes question stopwords', async () => {
  const { buildFts5Query } = await import(utilsUrl.href);
  assert.equal(buildFts5Query('What is an FVG?'), '"fvg"');
  assert.equal(buildFts5Query('How does an order-block work?'), '"order" AND "block"');
  assert.equal(buildFts5Query('ICT\'s liquidity'), '"ict" AND "liquidity"');
  assert.equal(buildFts5Query('") OR vault_fts MATCH("*'), '"vault" AND "fts" AND "match"');
});

test('timestamped R2 evidence preserves exact segment offsets inside a matched range', async () => {
  const { extractTimedSegments } = await import(utilsUrl.href);
  const transcript = [
    '3:45:29 Earlier context',
    '',
    '3:45:40 First exact quote',
    '',
    '3:45:51 Second exact quote',
    '',
    '3:46:02 Outside the matched range',
  ].join('\n');
  assert.deepEqual(extractTimedSegments(transcript, 13540, 13551), [
    { timestamp: '3:45:40', seconds: 13540, text: 'First exact quote' },
    { timestamp: '3:45:51', seconds: 13551, text: 'Second exact quote' },
  ]);
});

test('timestamped R2 evidence accepts MM:SS offsets beyond 99 minutes', async () => {
  const { extractTimedSegments, tsToSeconds } = await import(utilsUrl.href);
  const transcript = [
    '117:27 First long-minute quote',
    '117:30 Second long-minute quote',
  ].join('\n');
  assert.equal(tsToSeconds('117:27'), 7047);
  assert.deepEqual(extractTimedSegments(transcript, 7047, 7050), [
    { timestamp: '117:27', seconds: 7047, text: 'First long-minute quote' },
    { timestamp: '117:30', seconds: 7050, text: 'Second long-minute quote' },
  ]);
});

test('timestamped R2 extraction does not silently clip complete ranges at 24 segments', async () => {
  const { extractTimedSegments } = await import(utilsUrl.href);
  const transcript = Array.from(
    { length: 26 },
    (_, seconds) => `0:${String(seconds).padStart(2, '0')} segment ${seconds}`,
  ).join('\n');
  const segments = extractTimedSegments(transcript, 0, 25);
  assert.equal(segments.length, 26);
  assert.deepEqual(segments.at(-1), { timestamp: '0:25', seconds: 25, text: 'segment 25' });
});

test('DeepSeek SSE decoding preserves JSON split across arbitrary network chunks', async () => {
  const { createDeepSeekSseDecoder } = await import(utilsUrl.href);
  assert.equal(typeof createDeepSeekSseDecoder, 'function');

  const source = [
    'data: {"choices":[{"delta":{"content":"Fair value "}}]}',
    '',
    'data: {"choices":[{"delta":{"content":"gap."}}]}',
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  const bytes = new TextEncoder().encode(source);
  const decoder = createDeepSeekSseDecoder();
  let answer = '';
  for (const [start, end] of [[0, 9], [9, 31], [31, 58], [58, 77], [77, bytes.length]]) {
    answer += decoder.push(bytes.slice(start, end));
  }
  answer += decoder.flush();

  assert.equal(answer, 'Fair value gap.');
});

test('authenticated timestamped answers stream framed events and cache after completion', async (t) => {
  const answer = 'Liquidity rests above old highs and below old lows.';
  const modelPayload = JSON.stringify({ answer, evidence_ids: ['E1'] });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: modelPayload }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  let deepSeekRequest;
  installAuthenticatedFetch(t, async (url, options) => {
    assert.equal(url, 'https://api.deepseek.com/chat/completions');
    deepSeekRequest = JSON.parse(options.body);
    return new Response(streamFromText(upstream), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  });

  const writes = [];
  const waits = [];
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return null; },
      async put(...args) { writes.push(args); },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({
    request,
    env,
    waitUntil(promise) { waits.push(Promise.resolve(promise)); },
  });
  const body = await response.text();
  await Promise.all(waits);

  assert.equal(response.status, 200);
  assert.match(response.headers.get('Content-Type'), /text\/event-stream/);
  assert.match(body, /"type":"delta"/);
  assert.match(body, new RegExp(answer.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(body, /"type":"done"/);
  assert.match(body, /"remaining":9/);
  assert.match(body, /"plan":"free"/);
  assert.match(body, /"limit":10/);
  assert.match(body, /"dailyReset":false/);
  assert.match(deepSeekRequest.messages[1].content, /\[E1 \| 1:30 \| https:\/\/youtu\.be\/video123\?t=90\]/);
  assert.match(deepSeekRequest.messages[1].content, /Liquidity rests above old highs/);
  assert.doesNotMatch(deepSeekRequest.messages[1].content, /Outside the selected chunk/);
  assert.equal(writes.length, 1, 'a completed answer longer than 40 characters must be cached');
  const [key, payload, options] = writes[0];
  assert.match(key, /^qa:[0-9a-f]{64}$/);
  assert.deepEqual(JSON.parse(payload), {
    v: 1,
    corpus: 'chunks-0e405ddd9318345f6c507f540cfb90c2c88d5c540cdf5292b4c871ccbb7e2eba:transcripts-12bc027354b9100b3d9e54abf15b9920bc8e32a1e9e024cec501d8c62ce007a7',
    model: 'deepseek-v4-flash',
    prompt: 'grounded-json-v1',
    retrieval: 'hybrid-vector-fts-exact-r2-v2',
    maxOutputChars: 4000,
    grounding: 'exact-r2',
    answer,
    sources: [{
      evidence_id: 'E1',
      video_id: 'video123',
      playlist: 'Core Content',
      title: 'Liquidity lesson',
      timestamp: '1:30',
      seconds: 90,
      url: 'https://youtu.be/video123?t=90',
      quote: 'Liquidity rests above old highs and below old lows.',
    }],
    remaining: 9,
    plan: 'free',
    limit: 10,
    dailyReset: false,
  });
  assert.deepEqual(options, { expirationTtl: 86400 });
  assert.equal(db.runs.length, 2, 'success reserves one credit and writes one analytics row');
  assert.match(db.runs[1].sql, /INSERT INTO chat_log/);
  assert.match(db.runs[1].params[0], /^[0-9a-f]{64}$/);
  assert.doesNotMatch(JSON.stringify(db.runs[1].params), /Where does liquidity rest/i);
  assert.equal(db.runs[1].params[1], 'free');
  assert.equal(db.runs[1].params[3], 0);
});

test('double-escaped gateway JSON is normalized before grounded validation', async (t) => {
  // OpenCode Go (OpenAI-compatible gateway) streams deepseek-v4-flash deltas
  // with double-escaped JSON: {\"answer\":\"...\"} instead of {"answer":"..."}.
  // The server must normalize the escapes, then validate and stream normally.
  const answer = 'Liquidity rests above old highs and below old lows.';
  const escapedPayload = JSON.stringify({ answer, evidence_ids: ['E1'] }).replaceAll('"', '\\"');
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: escapedPayload }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  let deepSeekRequest;
  installAuthenticatedFetch(t, async (url, options) => {
    assert.equal(url, 'https://api.deepseek.com/chat/completions');
    deepSeekRequest = JSON.parse(options.body);
    return new Response(streamFromText(upstream), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  });

  const writes = [];
  const waits = [];
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return null; },
      async put(...args) { writes.push(args); },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({
    request,
    env,
    waitUntil(promise) { waits.push(Promise.resolve(promise)); },
  });
  const body = await response.text();
  await Promise.all(waits);

  assert.equal(response.status, 200, 'double-escaped JSON must still produce a verified answer');
  assert.match(response.headers.get('Content-Type'), /text\/event-stream/);
  assert.match(body, /"type":"delta"/);
  assert.match(body, new RegExp(answer.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(body, /"type":"done"/);
  assert.equal(writes.length, 1, 'normalized completion must still be cached');
  const [key, payload] = writes[0];
  assert.match(key, /^qa:[0-9a-f]{64}$/);
  assert.equal(JSON.parse(payload).answer, answer);
  assert.equal(db.runs.length, 2, 'success reserves one credit and writes one analytics row');
  assert.equal(deepSeekRequest.model, 'deepseek-v4-flash');
});

test('cache keys isolate plan output class, model, prompt, and corpus contracts', async (t) => {
  const handlerSource = readFileSync(askUrl, 'utf8');
  const scopeSource = /const cacheScope = ([\s\S]*?);\r?\n\s*const cacheKey/.exec(handlerSource)?.[1] || '';
  for (const boundary of [
    'policy.maxOutputChars',
    'policy.maxTokens',
    'model:${model}',
    'TEMPERATURE',
    'PROMPT_VERSION',
    'CORPUS_VERSION',
    'top-k:${topK}',
    'min-vector-score:${minScore}',
    'context-chars:${maxContextChars}',
    'RETRIEVAL_VERSION',
  ]) {
    assert.ok(scopeSource.includes(boundary), `cache scope must bind ${boundary}`);
  }

  const modelPayload = JSON.stringify({
    answer: 'Liquidity can act as a draw on price when resting beyond prior extremes.',
    evidence_ids: ['E1'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: modelPayload }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  let deepSeekCalls = 0;
  installAuthenticatedFetch(t, async () => {
    deepSeekCalls += 1;
    return new Response(streamFromText(upstream), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  });

  const values = new Map();
  const writes = [];
  const cache = {
    async get(key) { return values.has(key) ? JSON.parse(values.get(key)) : null; },
    async put(key, value) {
      writes.push(key);
      values.set(key, value);
    },
  };
  const { onRequestPost } = await import(askUrl.href);
  const freeResponse = await onRequestPost({
    request: await authenticatedRequest('Where does liquidity rest?'),
    env: makeEnv(makeDb({ ftsResults: [MATCH] }), { CACHE: cache }),
  });
  const proResponse = await onRequestPost({
    request: await authenticatedRequest('Where does liquidity rest?'),
    env: makeEnv(makeDb({ plan: 'pro', ftsResults: [MATCH] }), { CACHE: cache }),
  });
  await freeResponse.text();
  await proResponse.text();

  assert.equal(deepSeekCalls, 2, 'Pro must not receive a Free/Premium cache entry');
  assert.equal(writes.length, 2);
  assert.notEqual(writes[0], writes[1]);
  assert.doesNotMatch(writes.join(' '), /Where does liquidity rest/i);
});

test('invalid supplied bearer tokens fail closed instead of receiving anonymous access', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  let fetched = false;
  globalThis.fetch = async () => {
    fetched = true;
    return new Response('should not be called', { status: 500 });
  };

  const db = makeDb();
  const env = {
    ALLOWED_ORIGINS: 'http://localhost:8788',
    SUPABASE_URL: 'https://tamevojmkrmttutkkuvo.supabase.co',
    RATE_LIMIT_SALT: 'test-rate-limit-salt',
    DEEPSEEK_API_KEY: 'test-only-key',
    CHAT_DB: db,
    CACHE: { async get() { return null; } },
  };
  const request = new Request('http://localhost:8788/api/ask', {
    method: 'POST',
    headers: {
      Authorization: 'Bearer definitely-not-a-jwt',
      'Content-Type': 'application/json',
      Origin: 'http://localhost:8788',
      'CF-Connecting-IP': '203.0.113.11',
    },
    body: JSON.stringify({ question: 'What is liquidity?' }),
  });
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 401);
  assert.equal(fetched, false);
  assert.equal(db.runs.length, 0);
});

test('authenticated entitlement status reports the server plan and remaining credits', async (t) => {
  installAuthenticatedFetch(t);
  const db = makeDb({ questionsUsed: 3 });
  const env = makeEnv(db);
  const request = new Request('http://localhost:8788/api/ask', {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${await signedAccessToken()}`,
      Origin: 'http://localhost:8788',
    },
  });
  const module = await import(askUrl.href);
  assert.equal(typeof module.onRequestGet, 'function');
  const response = await module.onRequestGet({ request, env });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    plan: 'free',
    remaining: 7,
    limit: 10,
    dailyReset: false,
  });
});

test('atomic lifetime free quota denial blocks DeepSeek before upstream cost', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });

  const db = makeDb({ reservationChanges: 0, questionsUsed: 10 });
  const env = makeEnv(db);
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });
  const payload = await response.json();

  assert.equal(response.status, 429);
  assert.match(payload.error, /10 questions per account/i);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 1);
  assert.match(db.runs[0].sql, /ON CONFLICT[\s\S]+DO UPDATE[\s\S]+WHERE/i);
  assert.equal(db.runs[0].params[1], 'free');
  assert.equal(db.runs[0].params[2], 'lifetime', 'free allowance must never reset daily');
});

test('exact quota SQL keeps free lifetime usage and resets paid daily usage', async () => {
  const { reserveUsage } = await import(askUrl.href);
  const database = new DatabaseSync(':memory:');
  database.exec(`CREATE TABLE chat_usage_scoped (
    user_id TEXT NOT NULL,
    entitlement_scope TEXT NOT NULL,
    period_key TEXT NOT NULL,
    questions_used INTEGER NOT NULL DEFAULT 0,
    first_question_at INTEGER,
    last_question_at INTEGER,
    PRIMARY KEY (user_id, entitlement_scope, period_key)
  )`);
  const env = {
    CHAT_DB: {
      prepare(sql) {
        return {
          bind(...params) {
            const statement = database.prepare(sql);
            return {
              async run() {
                const result = statement.run(...params);
                return { meta: { changes: Number(result.changes) } };
              },
              async first() { return statement.get(...params) || null; },
            };
          },
        };
      },
    },
  };
  const free = { questions: 5, dailyReset: false };
  const paid = { questions: 2, dailyReset: true };
  const dayOne = Date.UTC(2026, 7, 9, 12);
  const dayTwo = Date.UTC(2026, 7, 10, 12);

  for (let count = 1; count <= 5; count += 1) {
    const result = await reserveUsage(env, { userId: 'free-user', scope: 'free' }, free, dayOne + count);
    assert.equal(result.allowed, true);
    assert.equal(result.used, count);
  }
  assert.equal((await reserveUsage(env, { userId: 'free-user', scope: 'free' }, free, dayOne + 100)).allowed, false);
  assert.equal((await reserveUsage(env, { userId: 'free-user', scope: 'free' }, free, dayTwo)).allowed, false);

  assert.equal((await reserveUsage(env, { userId: 'paid-user', scope: 'premium' }, paid, dayOne)).used, 1);
  assert.equal((await reserveUsage(env, { userId: 'paid-user', scope: 'premium' }, paid, dayOne + 1)).used, 2);
  assert.equal((await reserveUsage(env, { userId: 'paid-user', scope: 'premium' }, paid, dayOne + 2)).allowed, false);
  assert.equal((await reserveUsage(env, { userId: 'paid-user', scope: 'premium' }, paid, dayTwo)).used, 1);
  database.close();
});

test('scoped quota schema coexists with a legacy chat_usage table', async () => {
  const { reserveUsage } = await import(askUrl.href);
  const database = new DatabaseSync(':memory:');
  database.exec(`CREATE TABLE chat_usage (
    user_id TEXT NOT NULL,
    day_start INTEGER NOT NULL,
    questions_used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day_start)
  )`);
  database.exec(readFileSync(schemaUrl, 'utf8'));
  const env = {
    CHAT_DB: {
      prepare(sql) {
        return {
          bind(...params) {
            const statement = database.prepare(sql);
            return {
              async run() {
                const result = statement.run(...params);
                return { meta: { changes: Number(result.changes) } };
              },
              async first() { return statement.get(...params) || null; },
            };
          },
        };
      },
    },
  };

  const reservation = await reserveUsage(
    env,
    { userId: 'migration-safe-user', scope: 'free' },
    { questions: 5, dailyReset: false },
    Date.UTC(2026, 7, 10, 12),
  );
  assert.equal(reservation.allowed, true);
  assert.equal(database.prepare('SELECT COUNT(*) AS count FROM chat_usage').get().count, 0);
  assert.deepEqual(
    { ...database.prepare('SELECT entitlement_scope, period_key, questions_used FROM chat_usage_scoped').get() },
    { entitlement_scope: 'free', period_key: 'lifetime', questions_used: 1 },
  );
  database.close();
});

test('free, Premium, and Pro usage windows are isolated for upgrades and UTC rollover', async () => {
  const { reserveUsage } = await import(askUrl.href);
  const database = new DatabaseSync(':memory:');
  database.exec(`CREATE TABLE chat_usage_scoped (
    user_id TEXT NOT NULL,
    entitlement_scope TEXT NOT NULL,
    period_key TEXT NOT NULL,
    questions_used INTEGER NOT NULL DEFAULT 0,
    first_question_at INTEGER,
    last_question_at INTEGER,
    PRIMARY KEY (user_id, entitlement_scope, period_key)
  )`);
  const env = {
    CHAT_DB: {
      prepare(sql) {
        return {
          bind(...params) {
            const statement = database.prepare(sql);
            return {
              async run() {
                const result = statement.run(...params);
                return { meta: { changes: Number(result.changes) } };
              },
              async first() { return statement.get(...params) || null; },
            };
          },
        };
      },
    },
  };
  const free = { questions: 5, dailyReset: false };
  const premium = { questions: 100, dailyReset: true };
  const pro = { questions: 500, dailyReset: true };
  const dayOne = Date.UTC(2026, 7, 9, 12);
  const dayTwo = Date.UTC(2026, 7, 10, 12);
  const userId = 'upgrade-user';

  for (let count = 1; count <= 3; count += 1) {
    assert.equal((await reserveUsage(env, { userId, scope: 'free' }, free, dayOne + count)).used, count);
  }
  assert.equal((await reserveUsage(env, { userId, scope: 'premium' }, premium, dayOne)).used, 1);
  assert.equal((await reserveUsage(env, { userId, scope: 'pro' }, pro, dayOne)).used, 1);
  assert.equal((await reserveUsage(env, { userId, scope: 'premium' }, premium, dayTwo)).used, 1);
  assert.equal((await reserveUsage(env, { userId, scope: 'free' }, free, dayTwo)).used, 4);

  const rows = database.prepare(
    'SELECT entitlement_scope, period_key, questions_used FROM chat_usage_scoped ORDER BY entitlement_scope, period_key',
  ).all().map((row) => ({ ...row }));
  assert.deepEqual(rows, [
    { entitlement_scope: 'free', period_key: 'lifetime', questions_used: 4 },
    { entitlement_scope: 'premium', period_key: '2026-08-09', questions_used: 1 },
    { entitlement_scope: 'premium', period_key: '2026-08-10', questions_used: 1 },
    { entitlement_scope: 'pro', period_key: '2026-08-09', questions_used: 1 },
  ]);
  database.close();
});

test('refund removes only the reserved entitlement scope and period', async () => {
  const { reserveUsage, refundUsage } = await import(askUrl.href);
  const database = new DatabaseSync(':memory:');
  database.exec(`CREATE TABLE chat_usage_scoped (
    user_id TEXT NOT NULL,
    entitlement_scope TEXT NOT NULL,
    period_key TEXT NOT NULL,
    questions_used INTEGER NOT NULL DEFAULT 0,
    first_question_at INTEGER,
    last_question_at INTEGER,
    PRIMARY KEY (user_id, entitlement_scope, period_key)
  )`);
  const env = {
    CHAT_DB: {
      prepare(sql) {
        return {
          bind(...params) {
            const statement = database.prepare(sql);
            return {
              async run() {
                const result = statement.run(...params);
                return { meta: { changes: Number(result.changes) } };
              },
              async first() { return statement.get(...params) || null; },
            };
          },
        };
      },
    },
  };
  const now = Date.UTC(2026, 7, 9, 12);
  const key = { userId: 'refund-user' };
  await reserveUsage(env, { ...key, scope: 'free' }, { questions: 5, dailyReset: false }, now);
  const premiumReservation = await reserveUsage(
    env,
    { ...key, scope: 'premium' },
    { questions: 100, dailyReset: true },
    now,
  );
  await refundUsage(env, { ...key, scope: 'premium' }, premiumReservation);

  const rows = database.prepare(
    'SELECT entitlement_scope, questions_used FROM chat_usage_scoped ORDER BY entitlement_scope',
  ).all().map((row) => ({ ...row }));
  assert.deepEqual(rows, [
    { entitlement_scope: 'free', questions_used: 1 },
    { entitlement_scope: 'premium', questions_used: 0 },
  ]);
  database.close();
});

test('missing bearer session fails closed before database or upstream work', async () => {
  let fetched = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    fetched = true;
    return new Response('should not be called', { status: 500 });
  };
  try {
    const db = makeDb();
    const env = makeEnv(db);
    const request = new Request('http://localhost:8788/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'http://localhost:8788' },
      body: JSON.stringify({ question: 'What is market structure?' }),
    });
    const { onRequestPost } = await import(askUrl.href);
    const response = await onRequestPost({ request, env });

    assert.equal(response.status, 401);
    assert.equal(fetched, false);
    assert.equal(db.runs.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('missing timestamped evidence refunds credit and blocks DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });

  const db = makeDb({ ftsResults: [] });
  const env = makeEnv(db);
  const request = await authenticatedRequest('An obscure unsupported concept');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });
  const payload = await response.json();

  assert.equal(response.status, 422);
  assert.match(payload.error, /No matching timestamped vault evidence/i);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2, 'reservation must be refunded when evidence is unavailable');
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('R2 evidence ranges that exceed the complete-context budget fail closed before DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    const completion = JSON.stringify({ answer: 'This must not be released.', evidence_ids: ['E1'] });
    const upstream = [
      `data: ${JSON.stringify({ choices: [{ delta: { content: completion }, finish_reason: 'stop' }] })}`,
      '',
      'data: [DONE]',
      '',
    ].join('\n');
    return new Response(streamFromText(upstream), { status: 200 });
  });
  const transcript = Array.from(
    { length: 26 },
    (_, seconds) => `0:${String(seconds).padStart(2, '0')} segment ${seconds} ${'x'.repeat(420)}`,
  ).join('\n');
  const sourceFile = 'fixtures/long-range.md';
  const r2Key = await contentAddressedR2Key(sourceFile, transcript);
  const db = makeDb({
    sourceFile,
    r2Key,
    ftsResults: [{
      chunk_id: 'chunk-long-range',
      title: 'Long range',
      video_id: 'video123',
      playlist: 'Core',
      start_ts: '0:00',
      end_ts: '0:25',
      start_seconds: 0,
      end_seconds: 25,
      content: 'liquidity range',
    }],
  });
  const request = await authenticatedRequest('Explain liquidity');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({
    request,
    env: makeEnv(db, {
      VAULT_R2: {
        async get(key) {
          assert.equal(key, r2Key);
          return { async text() { return transcript; } };
        },
      },
    }),
  });

  assert.equal(response.status, 422);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2);
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('R2 evidence with a missing exact end boundary fails closed before DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });
  const db = makeDb({
    ftsResults: [{
      ...MATCH,
      end_ts: '1:52',
      end_seconds: 112,
    }],
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env: makeEnv(db) });

  assert.equal(response.status, 422);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2);
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('R2 body tampering fails content-address verification before DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });

  const tamperedTranscript = TIMED_TRANSCRIPT.replace('old highs', 'altered highs');
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    VAULT_R2: {
      async get() { return { async text() { return tamperedTranscript; } }; },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 502);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2);
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('non-monotonic R2 timestamp ranges fail closed before DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });

  const transcript = [
    '0:00 range start',
    '0:02 moves forward',
    '0:01 moves backward',
    '0:03 range end',
  ].join('\n');
  const malformedRange = {
    ...MATCH,
    start_ts: '0:00',
    end_ts: '0:03',
    start_seconds: 0,
    end_seconds: 3,
  };
  const sourceFile = 'fixtures/non-monotonic.md';
  const r2Key = await contentAddressedR2Key(sourceFile, transcript);
  const db = makeDb({ sourceFile, r2Key, ftsResults: [malformedRange] });
  const env = makeEnv(db, {
    VAULT_R2: { async get() { return { async text() { return transcript; } }; } },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2);
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('weak vector matches refund credit and never reach DeepSeek', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    return new Response('should not be called', { status: 500 });
  });

  const db = makeDb();
  const env = makeEnv(db, {
    AI: { async run() { return { data: [[0.1, 0.2]] }; } },
    VECTORIZE: {
      async query() {
        return {
          matches: [{
            id: 'chunk-1',
            score: 0.65,
            metadata: {
              contentType: 'transcript_chunk',
              video_id: MATCH.video_id,
              playlist: MATCH.playlist,
              title: MATCH.title,
              start_ts: MATCH.start_ts,
              end_ts: MATCH.end_ts,
              start_seconds: MATCH.start_seconds,
              end_seconds: MATCH.end_seconds,
            },
          }],
        };
      },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.equal(deepSeekFetched, false);
  assert.equal(db.runs.length, 2, 'weak evidence must refund the reservation');
});

test('fabricated model evidence IDs are refused, refunded, and never cached', async (t) => {
  const fabricated = JSON.stringify({
    answer: 'Price is drawn toward external liquidity.',
    evidence_ids: ['E999'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: fabricated }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const writes = [];
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return null; },
      async put(...args) { writes.push(args); },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /verified source evidence/i);
  assert.equal(writes.length, 0);
  assert.equal(db.runs.length, 2, 'invalid model evidence must refund the reservation');
});

test('quotes, timestamps, and links inside the answer are stripped, not fabricated', async (t) => {
  const fabricated = JSON.stringify({
    answer: 'ICT said at 1:30 that "the moon controls liquidity" and you can verify at https://plugict.com.',
    evidence_ids: ['E1'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: fabricated }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db);
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  // Grounding is enforced by the evidence-ID check; forbidden characters in
  // the answer body are stripped server-side (the server attaches exact
  // source excerpts itself).
  assert.equal(response.status, 200);
  const body = await response.text();
  // The fabricated URL, timestamp, and quote marks are stripped from the
  // ANSWER body; plain words remain (grounding is enforced by the
  // evidence-ID check). Source cards legitimately carry timestamps/URLs.
  const delta = JSON.parse(/data: ({"type":"delta".*})\n/.exec(body)[1]);
  assert.doesNotMatch(delta.content, /plugict\.com/);
  assert.doesNotMatch(delta.content, /1:30/);
  assert.doesNotMatch(delta.content, /"moon controls liquidity"/);
  assert.match(delta.content, /moon controls liquidity/);
  assert.match(body, /"type":"done"/);
  assert.equal(db.runs.length, 2, 'success reserves one credit and writes analytics');
  assert.match(db.runs[1].sql, /INSERT INTO chat_log/, 'second run is analytics, NOT a refund');
});

test('evidence IDs excluded by the prompt budget cannot be guessed by the model', async (t) => {
  const transcript = Array.from({ length: 24 }, (_, seconds) => (
    `0:${String(seconds).padStart(2, '0')} This is a deliberately long exact evidence segment number ${seconds} about liquidity and price delivery.`
  )).join('\n');
  const matches = Array.from({ length: 4 }, (_, index) => ({
    ...MATCH,
    chunk_id: `chunk-${index + 1}`,
    start_ts: '0:00',
    end_ts: '0:23',
    start_seconds: 0,
    end_seconds: 23,
  }));
  const r2Rows = Object.fromEntries(await Promise.all(matches.map(async (match) => {
    const sourceFile = `fixtures/${match.chunk_id}.md`;
    return [match.chunk_id, {
      source_file: sourceFile,
      r2_key: await contentAddressedR2Key(sourceFile, transcript),
    }];
  })));
  const validR2Keys = new Set(Object.values(r2Rows).map((row) => row.r2_key));
  const guessed = JSON.stringify({
    answer: 'Liquidity is used in price delivery.',
    evidence_ids: ['E73'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: guessed }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const db = makeDb({ ftsResults: matches, r2Rows });
  const env = makeEnv(db, {
    VAULT_R2: {
      async get(key) {
        assert.equal(validR2Keys.has(key), true);
        return { async text() { return transcript; } };
      },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /verified source evidence/i);
  assert.equal(db.runs.length, 2, 'out-of-budget evidence must refund the reservation');
});

test('DeepSeek length truncation is refused and refunded even when partial JSON parses', async (t) => {
  const partial = JSON.stringify({
    answer: 'Liquidity is resting above the old high.',
    evidence_ids: ['E1'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: partial }, finish_reason: 'length' }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db);
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /complete verified answer/i);
  assert.equal(db.runs.length, 2, 'truncated output must refund the reservation');
});

test('DeepSeek DONE without an explicit stop reason is refused and refunded', async (t) => {
  const apparentlyComplete = JSON.stringify({
    answer: 'Liquidity is resting above the old high.',
    evidence_ids: ['E1'],
  });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: apparentlyComplete } }] })}`,
    '',
    'data: [DONE]',
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db);
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.match((await response.json()).error, /complete verified answer/i);
  assert.equal(db.runs.length, 2, 'missing terminal reason must refund the reservation');
});

test('OpenCode Go usage metadata after [DONE] is accepted', async () => {
  const { createDeepSeekSseDecoder } = await import(utilsUrl.href);
  const decoder = createDeepSeekSseDecoder();
  const source = [
    'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
    '',
    'data: [DONE]',
    '',
    'data: {"choices":[],"cost":"0"}',
    '',
  ].join(String.fromCharCode(10));
  const answer = decoder.push(new TextEncoder().encode(source)) + decoder.flush();
  assert.equal(answer, 'ok');
  assert.equal(decoder.doneSeen(), true);
  assert.equal(decoder.finishReason(), 'stop');
  assert.equal(decoder.malformed(), false);
});

test('trailing events after [DONE] fail closed and refund', async (t) => {
  const completion = JSON.stringify({ answer: 'Liquidity rests above old highs.', evidence_ids: ['E1'] });
  const upstream = [
    `data: ${JSON.stringify({ choices: [{ delta: { content: completion }, finish_reason: 'stop' }] })}`,
    '',
    'data: [DONE]',
    '',
    `data: ${JSON.stringify({ choices: [{ delta: { content: 'TRAILING' } }] })}`,
    '',
  ].join('\n');
  installAuthenticatedFetch(t, async () => new Response(streamFromText(upstream), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const writes = [];
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return null; },
      async put(...args) { writes.push(args); },
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 422);
  assert.equal(writes.length, 0, 'post-terminal streams must never be cached');
  assert.equal(db.runs.length, 2, 'post-terminal streams must refund the reservation');
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped/);
});

test('forged cache envelopes are treated as a miss, deleted, and regenerated', async (t) => {
  let deepSeekFetched = false;
  installAuthenticatedFetch(t, async () => {
    deepSeekFetched = true;
    const completion = JSON.stringify({ answer: 'Liquidity rests above old highs and below old lows.', evidence_ids: ['E1'] });
    const upstream = [
      `data: ${JSON.stringify({ choices: [{ delta: { content: completion }, finish_reason: 'stop' }] })}`,
      '',
      'data: [DONE]',
      '',
    ].join('\n');
    return new Response(streamFromText(upstream), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  });

  const deleted = [];
  const forged = {
    v: 1,
    corpus: 'stale-corpus',
    model: 'deepseek-v4-flash',
    prompt: 'grounded-json-v1',
    retrieval: 'hybrid-vector-fts-exact-r2-v2',
    maxOutputChars: 4000,
    grounding: 'exact-r2',
    answer: 'x'.repeat(4500),
    sources: [],
  };
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return forged; },
      async delete(key) { deleted.push(key); },
      async put() {},
    },
  });
  const request = await authenticatedRequest('Where does liquidity rest?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });
  const body = await response.text();

  assert.equal(response.status, 200);
  assert.equal(deepSeekFetched, true, 'a forged cache entry must not short-circuit generation');
  assert.equal(deleted.length, 1, 'the forged entry must be deleted');
  assert.match(body, /"type":"delta"/);
});

test('a failed refund surfaces 503 instead of silently consuming the credit', async (t) => {
  installAuthenticatedFetch(t, async () => new Response('should not be called', { status: 500 }));
  const base = makeDb({ ftsResults: [] });
  const throwingDb = {
    prepare(sql) {
      if (sql.includes('UPDATE chat_usage_scoped')) {
        return { bind() { return { run() { throw new Error('ledger unavailable'); } }; } };
      }
      return base.prepare(sql);
    },
  };
  const env = makeEnv(throwingDb);
  const request = await authenticatedRequest('An unsupported concept');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /usage ledger could not be finalized/i);
});

test('mid-stream DeepSeek failure releases no partial answer, refunds, and skips cache', async (t) => {
  const upstream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(
        `data: ${JSON.stringify({ choices: [{ delta: { content: 'Partial answer' } }] })}\n\n`,
      ));
      controller.error(new Error('upstream stream broke'));
    },
  });
  installAuthenticatedFetch(t, async () => new Response(upstream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));

  const writes = [];
  const db = makeDb({ ftsResults: [MATCH] });
  const env = makeEnv(db, {
    CACHE: {
      async get() { return null; },
      async put(...args) { writes.push(args); },
    },
  });
  const request = await authenticatedRequest('What is liquidity?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });
  const payload = await response.json();

  assert.equal(response.status, 502);
  assert.match(payload.error, /stream interrupted/i);
  assert.equal(writes.length, 0);
  assert.equal(db.runs.length, 2, 'stream failure must refund the reservation');
});

test('upstream DeepSeek failure refunds an atomic quota reservation', async (t) => {
  installAuthenticatedFetch(t, async () => new Response('upstream unavailable', { status: 503 }));

  const db = makeDb({ reservationChanges: 1, questionsUsed: 1, ftsResults: [MATCH] });
  const env = makeEnv(db);
  const request = await authenticatedRequest('What is displacement?');
  const { onRequestPost } = await import(askUrl.href);
  const response = await onRequestPost({ request, env });

  assert.equal(response.status, 502);
  assert.equal(db.runs.length, 2, 'reservation and refund must both execute');
  assert.match(db.runs[1].sql, /UPDATE chat_usage_scoped[\s\S]+questions_used/i);
});
