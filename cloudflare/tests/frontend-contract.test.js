import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const beacon = readFileSync(new URL('../../assets/affiliate-analytics.js', import.meta.url), 'utf8');
const config = readFileSync(new URL('../../assets/affiliate-config.js', import.meta.url), 'utf8');
const dashboard = readFileSync(new URL('../../affiliate-dashboard.html', import.meta.url), 'utf8');
const landing = readFileSync(new URL('../../index.html', import.meta.url), 'utf8');

const APPROVED_CHECKOUT = 'https://buy.stripe.com/7sY14ob6qcTC057cTy6Ri02';
// Retired links stay named so a regression reads plainly in the failure output.
const RETIRED_RM2_CHECKOUT = '7sY14oeiC06QdVX9Hm6Ri01';
const RETIRED_2399_CHECKOUT = '9B64gA3DY1aUbNPcTy6Ri00';


test('landing excludes the retired RM2 checkout and uses the approved USD price', () => {
  assert.equal(landing.includes(RETIRED_RM2_CHECKOUT), false);
  assert.equal(landing.includes(RETIRED_2399_CHECKOUT), false);
  assert.equal(landing.includes('$18.89'), false);
  assert.match(landing, /priceUsd:\s*'\$18\.99'/);
  assert.match(landing, /"price":\s*"18\.99"/);
});

// An allowlist, not a denylist: naming each retired link only catches the ones
// someone remembered to list, and the page has already shipped two of them.
test('the approved link is the only checkout the landing can send a buyer to', () => {
  assert.match(landing, /stripeUrl:\s*'https:\/\/buy\.stripe\.com\/7sY14ob6qcTC057cTy6Ri02'/);
  const found = [...new Set(landing.match(/https:\/\/buy\.stripe\.com\/[A-Za-z0-9]+/g) ?? [])];
  assert.deepEqual(found, [APPROVED_CHECKOUT]);
});

test('landing has no visible referral banner implementation', () => {
  assert.equal(landing.includes('ref-banner'), false);
  assert.equal(landing.includes('Referred by an affiliate'), false);
});

test('beacon uses fresh-ref-only fetch keepalive transport', () => {
  assert.equal(beacon.includes('navigator.sendBeacon'), false);
  assert.match(beacon, /Content-Type.*text\/plain;charset=UTF-8/);
  assert.match(beacon, /keepalive:\s*true/);
  assert.match(beacon, /params\.get\('ref'\)/);
  assert.equal(beacon.includes("localStorage.getItem('plugict_ref')"), false);
});

test('production affiliate API config points only to the approved public endpoint', () => {
  assert.match(config, /window\.PLUGICT_AFFILIATE_API\s*=\s*'https:\/\/plugict-affiliate-production\.pages\.dev'/);
  assert.equal(config.includes('sk_live_'), false);
  assert.equal(config.includes('sk_test_'), false);
  assert.doesNotMatch(config, /Authorization|Bearer|api[_-]?key/i);
});

test('dashboard accepts session-only tokens and handles unavailable finance', () => {
  assert.equal(dashboard.includes("params.get('token')"), false);
  assert.equal(dashboard.includes('queryToken'), false);
  assert.match(dashboard, /sessionStorage\.getItem\(tokenKey\)/);
  assert.match(dashboard, /Not connected/);
});
