import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../scripts/build_cloudflare_site.mjs', import.meta.url), 'utf8');

test('static routes remain static and do not reference Functions', () => {
  assert.equal(source.includes('functions/'), false);
  assert.match(source, /public-files\.txt/);
});
