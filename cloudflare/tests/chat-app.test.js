import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import test from 'node:test';

const moduleUrl = new URL('../../assets/chat-app.js', import.meta.url);

test('Google sign-in returns to the same-origin chat dashboard', async () => {
  assert.equal(existsSync(moduleUrl), true, 'assets/chat-app.js must exist');
  const { createChatController } = await import(moduleUrl.href);
  let received;
  const auth = {
    async signInWithOAuth(options) {
      received = options;
      return { data: {}, error: null };
    },
  };
  const controller = createChatController({
    auth,
    location: { origin: 'https://feat-chatbar-dashboard.plugictmodify.pages.dev' },
  });

  await controller.signIn();

  assert.deepEqual(received, {
    provider: 'google',
    options: {
      redirectTo: 'https://feat-chatbar-dashboard.plugictmodify.pages.dev/chat/',
    },
  });
});

test('session restore and auth changes drive the dashboard gate', async () => {
  const { createChatController } = await import(moduleUrl.href);
  const restored = { access_token: 'token-1', user: { email: 'test@example.com' } };
  const changed = { access_token: 'token-2', user: { email: 'test@example.com' } };
  const rendered = [];
  let authChange;
  const subscription = { unsubscribe() {} };
  const auth = {
    async getSession() {
      return { data: { session: restored }, error: null };
    },
    onAuthStateChange(callback) {
      authChange = callback;
      return { data: { subscription } };
    },
    async signInWithOAuth() {
      return { data: {}, error: null };
    },
  };
  const controller = createChatController({
    auth,
    location: { origin: 'https://plugict.com' },
    onSession: (session) => rendered.push(session),
  });

  const session = await controller.restoreSession();
  const activeSubscription = controller.watchSession();
  authChange('TOKEN_REFRESHED', changed);
  authChange('SIGNED_OUT', null);

  assert.equal(session, restored);
  assert.equal(activeSubscription, subscription);
  assert.deepEqual(rendered, [restored, changed, null]);
});

test('sign-out clears the rendered session after Supabase confirms success', async () => {
  const { createChatController } = await import(moduleUrl.href);
  const rendered = [];
  let calls = 0;
  const controller = createChatController({
    auth: {
      async signOut() {
        calls += 1;
        return { error: null };
      },
    },
    location: { origin: 'https://plugict.com' },
    onSession: (session) => rendered.push(session),
  });

  await controller.signOut();

  assert.equal(calls, 1);
  assert.deepEqual(rendered, [null]);
});

test('failed sign-out does not fake a logged-out UI state', async () => {
  const { createChatController } = await import(moduleUrl.href);
  const rendered = [];
  const expected = new Error('network unavailable');
  const controller = createChatController({
    auth: {
      async signOut() {
        return { error: expected };
      },
    },
    location: { origin: 'https://plugict.com' },
    onSession: (session) => rendered.push(session),
  });

  await assert.rejects(controller.signOut(), expected);
  assert.deepEqual(rendered, []);
});

test('authenticated questions use the Supabase access token as a bearer header', async () => {
  const { createChatController } = await import(moduleUrl.href);
  const requests = [];
  const auth = {
    async getSession() {
      return {
        data: { session: { access_token: 'signed-access-token', user: { id: 'user-1' } } },
        error: null,
      };
    },
  };
  const controller = createChatController({
    auth,
    location: { origin: 'https://plugict.com' },
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return new Response(JSON.stringify({
        answer: 'A fair value gap is an imbalance.',
        sources: [],
        remaining: 4,
      }), { headers: { 'Content-Type': 'application/json' } });
    },
  });

  const result = await controller.ask('  What is a fair value gap?  ');

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/ask');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(requests[0].options.headers, {
    Authorization: 'Bearer signed-access-token',
    'Content-Type': 'application/json',
  });
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    question: 'What is a fair value gap?',
  });
  assert.deepEqual(result, {
    answer: 'A fair value gap is an imbalance.',
    sources: [],
    remaining: 4,
  });
});

test('authenticated entitlement lookup uses the Supabase bearer token', async () => {
  const { createChatController } = await import(moduleUrl.href);
  const requests = [];
  const controller = createChatController({
    auth: {
      async getSession() {
        return { data: { session: { access_token: 'signed-access-token' } }, error: null };
      },
    },
    location: { origin: 'https://plugict.com' },
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return new Response(JSON.stringify({ plan: 'pro', remaining: 499, limit: 500 }), {
        headers: { 'Content-Type': 'application/json' },
      });
    },
  });

  const result = await controller.getEntitlement();
  assert.deepEqual(requests, [{
    url: '/api/ask',
    options: { method: 'GET', headers: { Authorization: 'Bearer signed-access-token' } },
  }]);
  assert.deepEqual(result, { plan: 'pro', remaining: 499, limit: 500 });
});

test('question submission fails closed when no signed-in session exists', async () => {
  const { createChatController } = await import(moduleUrl.href);
  let fetched = false;
  const controller = createChatController({
    auth: {
      async getSession() {
        return { data: { session: null }, error: null };
      },
    },
    location: { origin: 'https://plugict.com' },
    fetchImpl: async () => {
      fetched = true;
      return new Response();
    },
  });

  await assert.rejects(controller.ask('What is liquidity?'), /Sign in required/);
  assert.equal(fetched, false);
});

test('framed SSE response survives arbitrary splits and preserves completion metadata', async () => {
  const { readAskResponse } = await import(moduleUrl.href);
  const encoder = new TextEncoder();
  const answer = 'Liquidity data: {"type":"done"} remains model text.';
  const wire = [
    `data: ${JSON.stringify({ type: 'delta', content: answer })}\n\n`,
    `data: ${JSON.stringify({
      type: 'done',
      sources: [{ title: 'Lesson', url: 'https://youtu.be/abc?t=90' }],
      remaining: 4,
      plan: 'free',
      limit: 5,
      dailyReset: false,
    })}\n\n`,
  ].join('');
  const bytes = encoder.encode(wire);
  const body = new ReadableStream({
    start(controller) {
      for (const [start, end] of [[0, 7], [7, 31], [31, 64], [64, 117], [117, bytes.length]]) {
        controller.enqueue(bytes.slice(start, end));
      }
      controller.close();
    },
  });
  const deltas = [];
  const response = new Response(body, {
    headers: { 'Content-Type': 'text/event-stream' },
  });

  const result = await readAskResponse(response, (delta) => deltas.push(delta));

  assert.equal(deltas.join(''), answer);
  assert.deepEqual(result, {
    answer,
    sources: [{ title: 'Lesson', url: 'https://youtu.be/abc?t=90' }],
    remaining: 4,
    plan: 'free',
    limit: 5,
    dailyReset: false,
  });
});

test('framed SSE error is not accepted as a successful truncated answer', async () => {
  const { readAskResponse } = await import(moduleUrl.href);
  const wire = [
    `data: ${JSON.stringify({ type: 'delta', content: 'Partial answer' })}\n\n`,
    `data: ${JSON.stringify({ type: 'error', error: 'AI stream interrupted' })}\n\n`,
  ].join('');
  const response = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(wire));
      controller.close();
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } });

  await assert.rejects(readAskResponse(response), /AI stream interrupted/);
});
