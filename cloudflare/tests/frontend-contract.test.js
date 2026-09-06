import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const beacon = readFileSync(new URL('../../assets/affiliate-analytics.js', import.meta.url), 'utf8');
const config = readFileSync(new URL('../../assets/affiliate-config.js', import.meta.url), 'utf8');
const dashboard = readFileSync(new URL('../../affiliate-dashboard.html', import.meta.url), 'utf8');

test('beacon uses fresh-ref-only fetch keepalive transport', () => {
  assert.equal(beacon.includes('navigator.sendBeacon'), false);
  assert.match(beacon, /Content-Type.*text\/plain;charset=UTF-8/);
  assert.match(beacon, /keepalive:\s*true/);
  assert.match(beacon, /params\.get\('ref'\)/);
  assert.equal(beacon.includes("localStorage.getItem('plugict_ref')"), false);
});

test('production affiliate API config preserves the configured public endpoint', () => {
  const endpoint = /window\.PLUGICT_AFFILIATE_API\s*=\s*'([^']*)'/.exec(config)?.[1];
  assert.equal(endpoint, 'https://plugict-affiliate-production.pages.dev');
  const url = new URL(endpoint);
  assert.equal(url.protocol, 'https:');
  assert.equal(url.username + url.password + url.search + url.hash, '');
});

test('dashboard accepts session-only tokens and handles unavailable finance', () => {
  assert.equal(dashboard.includes("params.get('token')"), false);
  assert.equal(dashboard.includes('queryToken'), false);
  assert.match(dashboard, /sessionStorage\.getItem\(tokenKey\)/);
  assert.match(dashboard, /Not connected/);
});
