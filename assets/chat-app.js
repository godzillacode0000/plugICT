function parseSsePayload(eventText) {
  const data = String(eventText || '')
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  try {
    return JSON.parse(data);
  } catch {
    throw new Error('AI response contained malformed stream metadata');
  }
}

async function responseError(response) {
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    message = body?.error || body?.message || message;
  } catch {
    // Keep the status-only error when the body is not JSON.
  }
  const error = new Error(message);
  error.status = response.status;
  return error;
}

export async function readAskResponse(response, onDelta = () => {}) {
  if (!response?.ok) throw await responseError(response);

  const contentType = response.headers.get('Content-Type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  if (!response.body) throw new Error('AI response body is missing');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let answer = '';
  let completion = null;

  function consume(eventText) {
    const payload = parseSsePayload(eventText);
    if (!payload) return;
    if (payload.type === 'delta') {
      if (completion) throw new Error('AI response continued after completion');
      if (typeof payload.content !== 'string') throw new Error('AI response delta is malformed');
      answer += payload.content;
      onDelta(payload.content);
      return;
    }
    if (payload.type === 'error') {
      throw new Error(payload.error || 'AI stream interrupted');
    }
    if (payload.type === 'done') {
      if (completion) throw new Error('AI response completed more than once');
      completion = {
        sources: Array.isArray(payload.sources) ? payload.sources : [],
        remaining: Number.isInteger(payload.remaining) ? payload.remaining : undefined,
        plan: typeof payload.plan === 'string' ? payload.plan : undefined,
        limit: Number.isInteger(payload.limit) ? payload.limit : undefined,
        dailyReset: typeof payload.dailyReset === 'boolean' ? payload.dailyReset : undefined,
      };
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    const events = pending.split(/\r?\n\r?\n/);
    pending = events.pop() || '';
    for (const eventText of events) consume(eventText);
  }

  pending += decoder.decode();
  if (pending.trim()) consume(pending);
  if (!completion) throw new Error('AI response ended before completion');

  return { answer, ...completion };
}

export function createChatController({
  auth,
  location = globalThis.location,
  fetchImpl = globalThis.fetch,
  onSession = () => {},
} = {}) {
  if (!auth) throw new TypeError('auth is required');
  if (!location?.origin) throw new TypeError('location.origin is required');
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl is required');

  return {
    async signIn() {
      const result = await auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${location.origin}/chat/` },
      });
      if (result?.error) throw result.error;
      return result?.data;
    },

    async restoreSession() {
      const result = await auth.getSession();
      if (result?.error) throw result.error;
      const session = result?.data?.session || null;
      onSession(session);
      return session;
    },

    watchSession() {
      const result = auth.onAuthStateChange((_event, session) => {
        onSession(session || null);
      });
      return result?.data?.subscription;
    },

    async signOut() {
      const result = await auth.signOut();
      if (result?.error) throw result.error;
      onSession(null);
    },

    async getEntitlement() {
      const sessionResult = await auth.getSession();
      if (sessionResult?.error) throw sessionResult.error;
      const accessToken = sessionResult?.data?.session?.access_token;
      if (!accessToken) throw new Error('Sign in required');
      const response = await fetchImpl('/api/ask', {
        method: 'GET',
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!response?.ok) throw await responseError(response);
      return response.json();
    },

    async ask(question, onDelta = () => {}) {
      const cleanQuestion = String(question || '').trim();
      if (!cleanQuestion) throw new Error('Enter a question first');
      if (cleanQuestion.length > 200) throw new Error('Question is limited to 200 characters');

      const sessionResult = await auth.getSession();
      if (sessionResult?.error) throw sessionResult.error;
      const accessToken = sessionResult?.data?.session?.access_token;
      if (!accessToken) throw new Error('Sign in required');

      const response = await fetchImpl('/api/ask', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: cleanQuestion }),
      });
      return readAskResponse(response, onDelta);
    },
  };
}
