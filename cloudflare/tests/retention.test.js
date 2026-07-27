import assert from 'node:assert/strict';
import test from 'node:test';
import { cleanupExpired } from '../retention-worker/src/index.js';

class FakeD1 {
  constructor(changes) { this.changes = [...changes]; this.calls = []; }
  prepare(sql) {
    const db = this;
    return { bind(...args) { return { async run() { db.calls.push({ sql, args }); return { meta: { changes: db.changes.shift() ?? 0 } }; } }; } };
  }
}

test('retention deletes only bounded expired click batches', async () => {
  const db = new FakeD1([1000, 1000, 3]);
  const result = await cleanupExpired(db, 100 * 86400);
  assert.equal(result.deleted, 2003);
  assert.equal(db.calls.length, 3);
  assert.match(db.calls[0].sql, /DELETE FROM affiliate_clicks/);
  assert.match(db.calls[0].sql, /created_at < \?1/);
  assert.equal(db.calls[0].args[0], (10 * 86400));
  assert.equal(db.calls[0].args[1], 1000);
});

test('retention has a hard five-batch run cap', async () => {
  const db = new FakeD1([1000, 1000, 1000, 1000, 1000, 1000]);
  const result = await cleanupExpired(db, 100 * 86400);
  assert.equal(result.deleted, 5000);
  assert.equal(db.calls.length, 5);
});

test('retention worker exposes no public fetch handler', async () => {
  const worker = await import('../retention-worker/src/index.js');
  assert.equal('fetch' in worker.default, false);
  assert.equal(typeof worker.default.scheduled, 'function');
});
