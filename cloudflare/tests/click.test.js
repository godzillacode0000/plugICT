import assert from 'node:assert/strict';
import test from 'node:test';
import { onRequestPost } from '../../functions/api/affiliate/click.js';

class FakeD1 {
  constructor() {
    this.codes = new Map([['test_001', { code: 'test_001', display_name: 'Test Affiliate', status: 'active' }]]);
    this.clicks = [];
  }
  prepare(sql) {
    const db = this;
    return {
      bind(...args) {
        return {
          async first() {
            if (sql.includes('FROM affiliate_codes')) return db.codes.get(args[0]) || null;
            return null;
          },
          async run() {
            if (sql.includes('INSERT OR IGNORE INTO affiliate_clicks')) {
              if (db.clicks.some((row) => row.click_id === args[0])) return { meta: { changes: 0 } };
              db.clicks.push({ click_id: args[0], affiliate_code: args[1], visitor_hash: args[2], path: args[3], referrer_host: args[4] });
              return { meta: { changes: 1 } };
            }
            return { meta: { changes: 0 } };
          },
        };
      },
    };
  }
}

function context(body, db = new FakeD1(), headers = {}) {
  return {
    request: new Request('https://preview.example/api/affiliate/click', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=UTF-8', ...headers },
      body,
    }),
    env: { DB: db, CLICK_HASH_SALT: 'test-salt', ALLOWED_ORIGINS: 'https://preview.example' },
  };
}

test('click ingestion accepts, deduplicates, and hashes visitor ids', async () => {
  const db = new FakeD1();
  const body = JSON.stringify({ code: 'TEST_001', click_id: 'click_001', visitor_id: 'visitor_123456', path: '/?x=1', referrer: 'https://Example.com/article' });
  assert.equal((await onRequestPost(context(body, db))).status, 204);
  assert.equal((await onRequestPost(context(body, db))).status, 204);
  assert.equal(db.clicks.length, 1);
  assert.equal(db.clicks[0].affiliate_code, 'test_001');
  assert.equal(db.clicks[0].path, '/');
  assert.equal(db.clicks[0].referrer_host, 'example.com');
  assert.equal(db.clicks[0].visitor_hash.length, 64);
  assert.equal(db.clicks[0].visitor_hash.includes('visitor_123456'), false);
});

test('unknown affiliate codes have the same empty response', async () => {
  const response = await onRequestPost(context(JSON.stringify({ code: 'unknown', click_id: 'click_002', visitor_id: 'visitor_123456' })));
  assert.equal(response.status, 204);
});

test('click endpoint rejects malformed and oversized bodies', async () => {
  assert.equal((await onRequestPost(context('{bad'))).status, 400);
  assert.equal((await onRequestPost(context('x'.repeat(4097)))).status, 413);
});

test('click endpoint has narrow OPTIONS support', async () => {
  const db = new FakeD1();
  const ctx = context('', db, { Origin: 'https://preview.example' });
  ctx.request = new Request(ctx.request.url, { method: 'OPTIONS', headers: { Origin: 'https://preview.example' } });
  const { onRequestOptions } = await import('../../functions/api/affiliate/click.js');
  const response = onRequestOptions(ctx);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://preview.example');
});
