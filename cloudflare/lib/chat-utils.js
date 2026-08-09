// PlugICT Chatbar — chat-specific utilities (no duplicates of cloudflare/lib/auth.js)
// Uses existing sha256Hex/hmacVisitorHash from ../lib/auth.js. No secrets here.

// ── Day bucket (UTC) for rate limiting ──────────────────────────────────
export function dayBucket(ts = Date.now()) {
  return Math.floor(ts / 86400000); // UTC days since epoch
}

// ── Timestamp helpers (transcript [MM:SS] / [H:MM:SS] offsets) ──────────
export function tsToSeconds(ts) {
  if (!ts) return 0;
  const parts = String(ts).trim().split(':');
  if ((parts.length !== 2 && parts.length !== 3)
    || parts.some((part) => !/^\d+$/.test(part))) return 0;
  const values = parts.map((part) => Number.parseInt(part, 10));
  if (parts.length === 2) {
    const [minutes, seconds] = values;
    return seconds < 60 ? minutes * 60 + seconds : 0;
  }
  const [hours, minutes, seconds] = values;
  return minutes < 60 && seconds < 60 ? hours * 3600 + minutes * 60 + seconds : 0;
}

export function deeplink(videoId, seconds) {
  return `https://youtu.be/${videoId}?t=${Math.max(0, Math.floor(seconds))}`;
}

// ── Safe FTS5 query builder ─────────────────────────────────────────────
const FTS5_STOPWORDS = new Set([
  'about', 'and', 'are', 'can', 'does', 'explain', 'for', 'from', 'how',
  'into', 'is', 'me', 'or', 'should', 'tell', 'that', 'the', 'this',
  'what', 'when', 'where', 'which', 'why', 'with', 'work', 'works',
]);

export function buildFts5Query(text, maxTerms = 6) {
  const tokens = String(text || '').toLowerCase().match(/[a-z0-9]+/g) || [];
  const terms = [];
  const seen = new Set();
  for (const token of tokens) {
    if (token.length <= 2 || FTS5_STOPWORDS.has(token) || seen.has(token)) continue;
    seen.add(token);
    terms.push(token);
    if (terms.length >= maxTerms) break;
  }
  // Tokens are restricted to ASCII alphanumerics, then quoted so punctuation
  // and FTS operators supplied by a user cannot alter MATCH grammar.
  return terms.map(term => `"${term}"`).join(' AND ');
}

export function extractTimedSegments(transcript, startSeconds, endSeconds, maxSegments = Number.POSITIVE_INFINITY) {
  const start = Math.max(0, Number(startSeconds) || 0);
  const end = Math.max(start, Number(endSeconds) || start);
  const segments = [];
  for (const line of String(transcript || '').split(/\r?\n/)) {
    const match = /^\s*(\d+:\d{2}(?::\d{2})?)\s+(.+?)\s*$/.exec(line);
    if (!match) continue;
    const seconds = tsToSeconds(match[1]);
    if (seconds < start || seconds > end) continue;
    segments.push({ timestamp: match[1], seconds, text: match[2] });
    if (segments.length >= maxSegments) break;
  }
  return segments;
}

// ── SSE stream helpers ──────────────────────────────────────────────────
// DeepSeek (OpenAI-compatible) SSE lines: data: {"choices":[{"delta":{"content":"..."}}]}
// Network chunks can split a JSON line at any byte, so parsing must retain the
// unfinished line between reads instead of treating each chunk independently.
export function createDeepSeekSseDecoder(decoder = new TextDecoder()) {
  let pending = '';
  let terminalSeen = false;
  let finishReason = null;
  let malformed = false;

  function parseLines(lines) {
    let out = '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const payload = trimmed.slice(5).trim();
      if (!payload) continue;
      if (payload === '[DONE]') {
        // Exactly one terminal event is required; anything after it — or a
        // second terminal marker — is a malformed stream and must fail closed.
        if (terminalSeen) malformed = true;
        terminalSeen = true;
        continue;
      }
      if (terminalSeen) {
        malformed = true;
        continue;
      }
      try {
        const parsed = JSON.parse(payload);
        const choice = parsed?.choices?.[0];
        if (typeof choice?.finish_reason === 'string') finishReason = choice.finish_reason;
        const delta = choice?.delta?.content;
        if (typeof delta === 'string') out += delta;
      } catch {
        malformed = true;
        // A malformed event contributes no text. Partial events never reach
        // this branch because the unfinished line remains in `pending`.
      }
    }
    return out;
  }

  return {
    push(chunk) {
      pending += decoder.decode(chunk, { stream: true });
      const lines = pending.split('\n');
      pending = lines.pop() || '';
      return parseLines(lines);
    },

    flush() {
      pending += decoder.decode();
      const lines = pending.split('\n');
      pending = '';
      return parseLines(lines);
    },

    doneSeen() { return terminalSeen; },
    finishReason() { return finishReason; },
    malformed() { return malformed; },
  };
}

export function sseDeltaEvent(content) {
  return `data: ${JSON.stringify({ type: 'delta', content })}\n\n`;
}

// Final client SSE event carrying source, quota, and plan metadata.
export function sseFinalEvent(sources, remaining, plan, limit, dailyReset) {
  return `data: ${JSON.stringify({ type: 'done', sources, remaining, plan, limit, dailyReset })}\n\n`;
}

export function sseErrorEvent(error) {
  return `data: ${JSON.stringify({ type: 'error', error })}\n\n`;
}
