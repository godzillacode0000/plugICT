import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const schema = readFileSync(new URL('../schema.sql', import.meta.url), 'utf8').toLowerCase();

test('D1 schema is analytics-only and privacy-safe', () => {
  assert.match(schema, /create table if not exists affiliate_codes/);
  assert.match(schema, /create table if not exists affiliate_clicks/);
  assert.match(schema, /token_hash text/);
  assert.match(schema, /visitor_hash text/);
  for (const prohibited of ['buyer_email', 'raw_ip', 'user_agent', 'stripe_id', 'commission_cents', 'payment_intent']) {
    assert.equal(schema.includes(prohibited), false, `prohibited schema field: ${prohibited}`);
  }
});
