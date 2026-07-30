import assert from 'node:assert/strict';
import test from 'node:test';
import { onRequestGet } from '../../functions/api/affiliate/stats.js';
import { sha256Hex } from '../lib/auth.js';

class FakeD1 {
  constructor(tokenHash) { this.tokenHash = tokenHash; }
  prepare(sql) {
    const db = this;
    return { bind(...args) {
      return {
        async first() {
          if (sql.includes('FROM affiliate_codes')) {
            if (args[0] !== db.tokenHash) return null;
            return { code: 'test_001', display_name: 'Test Affiliate', status: 'active', token_hash: db.tokenHash };
          }
          if (sql.includes('COUNT(*) AS clicks')) return { clicks: 7, unique_clicks: 5 };
          return null;
        },
      };
    }};
  }
}

function request(token, query = '') {
  return new Request(`https://preview.example/api/affiliate/stats${query}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

test('stats rejects missing tokens and token_hash NULL rows', async () => {
  const db = new FakeD1('');
  assert.equal((await onRequestGet({ request: request(''), env: { DB: db } })).status, 401);
  assert.equal((await onRequestGet({ request: request('not-a-real-token'), env: { DB: db } })).status, 401);
});

test('stats returns isolated click aggregates and null finance fields', async () => {
  const token = 'preview-token-123456789';
  const db = new FakeD1(await sha256Hex(token));
  const response = await onRequestGet({
    request: request(token, '?days=30'),
    env: { DB: db, ALLOWED_ORIGINS: 'https://preview.example' },
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const body = await response.json();
  assert.deepEqual(body.affiliate, { code: 'test_001', name: 'Test Affiliate' });
  assert.equal(body.referral_url, 'https://go.plugict.com/r/test_001');
  assert.equal(body.clicks, 7);
  assert.equal(body.unique_clicks, 5);
  assert.equal(body.purchases, null);
  assert.equal(body.conversion_rate, null);
  assert.equal(body.pending_commission_cents, null);
  assert.equal(body.finance_status, 'not_connected');
  assert.equal(JSON.stringify(body).includes(token), false);
});

test('stats enforces the 1-90 day range', async () => {
  const token = 'preview-token-123456789';
  const db = new FakeD1(await sha256Hex(token));
  assert.equal((await onRequestGet({ request: request(token, '?days=0'), env: { DB: db } })).status, 400);
  assert.equal((await onRequestGet({ request: request(token, '?days=91'), env: { DB: db } })).status, 400);
});
