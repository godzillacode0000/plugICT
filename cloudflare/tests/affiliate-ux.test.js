import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const attribution = readFileSync(new URL('../../assets/affiliate-attribution.js', import.meta.url), 'utf8');
const analytics = readFileSync(new URL('../../assets/affiliate-analytics.js', import.meta.url), 'utf8');
const APPROVED_CHECKOUT = 'https://buy.stripe.com/7sY14ob6qcTC057cTy6Ri02';
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

function runAttribution({ search = '', stored, now = 1_800_000_000_000 } = {}) {
  const values = new Map();
  if (stored !== undefined) values.set('plugict_ref', stored);
  const localStorage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
  class FixedDate extends Date {
    static now() { return now; }
  }
  const window = { location: { search } };

  vm.runInNewContext(attribution, {
    window,
    localStorage,
    Date: FixedDate,
    URL,
    URLSearchParams,
  });
  return { window, values };
}

function runAnalytics(search) {
  const fetches = [];
  const replacements = [];
  const events = [];
  const values = new Map();
  const location = { pathname: '/pricing', search, hash: '#buy' };
  const localStorage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
  const history = {
    state: { test: true },
    replaceState(state, title, url) {
      events.push('replace');
      replacements.push({ state, title, url });
    },
  };
  const crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000001' };
  const window = {
    PLUGICT_AFFILIATE_API: 'https://affiliate.example',
    location,
    history,
    crypto,
  };
  const fetch = (url, options) => {
    events.push('fetch');
    fetches.push({ url, options });
    return Promise.resolve({ ok: true });
  };

  vm.runInNewContext(analytics, {
    window,
    document: { referrer: 'https://example.com/article' },
    localStorage,
    history,
    crypto,
    fetch,
    URLSearchParams,
  });
  return { fetches, replacements, events };
}

test('fresh legacy ref links create a 30-day checkout attribution', () => {
  const now = 1_800_000_000_000;
  const { window, values } = runAttribution({ search: '?ref=AMIR_001', now });
  const stored = JSON.parse(values.get('plugict_ref'));

  assert.deepEqual(stored, { code: 'amir_001', expires_at: now + THIRTY_DAYS_MS });
  assert.equal(
    window.plugictStripeUrl(APPROVED_CHECKOUT),
    `${APPROVED_CHECKOUT}?client_reference_id=amir_001`,
  );
});

test('an unexpired stored attribution still reaches Stripe checkout', () => {
  const now = 1_800_000_000_000;
  const stored = JSON.stringify({ code: 'sarah_001', expires_at: now + 1 });
  const { window } = runAttribution({ stored, now });

  assert.equal(
    window.plugictStripeUrl(APPROVED_CHECKOUT),
    `${APPROVED_CHECKOUT}?client_reference_id=sarah_001`,
  );
});

test('expired, legacy, and malformed referral storage is safely cleared', () => {
  const now = 1_800_000_000_000;
  const staleValues = [
    JSON.stringify({ code: 'old_001', expires_at: now }),
    'legacy_001',
    '{not-json',
    JSON.stringify({ code: '../bad', expires_at: now + THIRTY_DAYS_MS }),
  ];

  for (const stored of staleValues) {
    const { window, values } = runAttribution({ stored, now });
    assert.equal(values.has('plugict_ref'), false);
    assert.equal(window.plugictStripeUrl, undefined);
  }
});

test('fresh-ref analytics initiates the click before cleaning only ref from the URL', () => {
  const { fetches, replacements, events } = runAnalytics('?utm_source=newsletter&ref=AMIR_001&campaign=launch');

  assert.deepEqual(events, ['fetch', 'replace']);
  assert.equal(fetches.length, 1);
  assert.equal(fetches[0].url, 'https://affiliate.example/api/affiliate/click');
  assert.equal(fetches[0].options.keepalive, true);
  assert.deepEqual(JSON.parse(fetches[0].options.body), {
    code: 'amir_001',
    click_id: '00000000-0000-4000-8000-000000000001',
    visitor_id: '00000000-0000-4000-8000-000000000001',
    path: '/pricing',
    referrer: 'https://example.com/article',
  });
  assert.deepEqual(replacements, [{
    state: { test: true },
    title: '',
    url: '/pricing?utm_source=newsletter&campaign=launch#buy',
  }]);
});

test('malformed ref values are cleaned without emitting click analytics', () => {
  const { fetches, replacements } = runAnalytics('?keep=1&ref=bad%20code');

  assert.equal(fetches.length, 0);
  assert.equal(replacements[0].url, '/pricing?keep=1#buy');
});
