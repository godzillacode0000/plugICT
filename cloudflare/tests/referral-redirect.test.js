import assert from 'node:assert/strict';
import test from 'node:test';
import { onRequestGet } from '../../functions/r/[code].js';

class FakeD1 {
  constructor(rows = {}) {
    this.rows = new Map(Object.entries(rows));
    this.queries = [];
  }

  prepare(sql) {
    const db = this;
    return {
      bind(code) {
        return {
          async first() {
            db.queries.push({ sql, code });
            const row = db.rows.get(code) || null;
            if (sql.includes("status = 'active'") && row?.status !== 'active') return null;
            return row;
          },
        };
      },
    };
  }
}

function context(code, db) {
  return {
    request: new Request(`https://go.plugict.com/r/${encodeURIComponent(code)}`),
    env: { DB: db },
    params: { code },
  };
}

async function redirectFor(code, db = new FakeD1()) {
  return onRequestGet(context(code, db));
}

test('active affiliate codes redirect to the canonical attributed landing', async () => {
  const db = new FakeD1({
    amir_001: { code: 'amir_001', display_name: 'Amir', status: 'active' },
  });
  const response = await redirectFor('AMIR_001', db);

  assert.equal(response.status, 302);
  assert.equal(response.headers.get('Location'), 'https://plugict.com/?ref=amir_001');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(db.queries.length, 1);
  assert.match(db.queries[0].sql, /status\s*=\s*'active'/);
  assert.equal(db.queries[0].code, 'amir_001');
});

test('unknown and inactive codes have the same non-enumerating redirect', async () => {
  const inactive = new FakeD1({
    paused_001: { code: 'paused_001', display_name: 'Paused', status: 'paused' },
  });
  const unknownResponse = await redirectFor('unknown_001', new FakeD1());
  const inactiveResponse = await redirectFor('paused_001', inactive);

  assert.equal(unknownResponse.status, 302);
  assert.equal(inactiveResponse.status, 302);
  assert.equal(unknownResponse.headers.get('Location'), 'https://plugict.com/');
  assert.equal(inactiveResponse.headers.get('Location'), 'https://plugict.com/');
});

test('malformed codes redirect home without querying D1', async () => {
  for (const code of ['', 'bad code', '../admin', 'x'.repeat(65)]) {
    const db = new FakeD1();
    const response = await redirectFor(code, db);
    assert.equal(response.status, 302);
    assert.equal(response.headers.get('Location'), 'https://plugict.com/');
    assert.equal(db.queries.length, 0);
  }
});
