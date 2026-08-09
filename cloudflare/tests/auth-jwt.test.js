import assert from 'node:assert/strict';
import test from 'node:test';
import { verifySupabaseJwt } from '../lib/auth.js';

const URL = 'https://abcdefghijklm.supabase.co';
const KID = '77e188ef-3c2c-4b39-aed1-240c80a78e78';
const encoder = new TextEncoder();
const b64u = (bytes) => Buffer.from(bytes)
  .toString('base64')
  .replace(/\+/g, '-')
  .replace(/\//g, '_')
  .replace(/=+$/, '');

const keyPair = await crypto.subtle.generateKey(
  { name: 'ECDSA', namedCurve: 'P-256' },
  true,
  ['sign', 'verify'],
);
const otherKeyPair = await crypto.subtle.generateKey(
  { name: 'ECDSA', namedCurve: 'P-256' },
  true,
  ['sign', 'verify'],
);
const publicJwk = {
  ...(await crypto.subtle.exportKey('jwk', keyPair.publicKey)),
  alg: 'ES256',
  kid: KID,
  use: 'sig',
  key_ops: ['verify'],
};

const base = {
  sub: 'user-123',
  email: 'k@plugict.com',
  aud: 'authenticated',
  role: 'authenticated',
  exp: Math.floor(Date.now() / 1000) + 3600,
  iss: `${URL}/auth/v1`,
};

async function signToken(payload, privateKey = keyPair.privateKey, header = {}) {
  const encodedHeader = b64u(encoder.encode(JSON.stringify({
    alg: 'ES256', typ: 'JWT', kid: KID, ...header,
  })));
  const encodedBody = b64u(encoder.encode(JSON.stringify(payload)));
  const input = `${encodedHeader}.${encodedBody}`;
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' },
    privateKey,
    encoder.encode(input),
  );
  return `${input}.${b64u(new Uint8Array(signature))}`;
}

function mockJwks(keys = [publicJwk], status = 200) {
  return async (url) => {
    assert.equal(url, `${URL}/auth/v1/.well-known/jwks.json`);
    return new Response(JSON.stringify({ keys }), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  };
}

test('valid Supabase ES256 JWT passes JWKS verification', async () => {
  const token = await signToken(base);
  const user = await verifySupabaseJwt(token, URL, mockJwks());
  assert.deepEqual(user, { userId: 'user-123', email: 'k@plugict.com' });
});

test('tampered payload fails closed', async () => {
  const token = await signToken(base);
  const parts = token.split('.');
  parts[1] = b64u(encoder.encode(JSON.stringify({ ...base, sub: 'attacker' })));
  assert.equal(await verifySupabaseJwt(parts.join('.'), URL, mockJwks()), null);
});

test('token signed by another private key fails closed', async () => {
  const token = await signToken(base, otherKeyPair.privateKey);
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks()), null);
});

test('expired token fails closed', async () => {
  const token = await signToken({ ...base, exp: Math.floor(Date.now() / 1000) - 60 });
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks()), null);
});

test('token from another Supabase project fails issuer pin', async () => {
  const token = await signToken({ ...base, iss: 'https://other-project.supabase.co/auth/v1' });
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks()), null);
});

test('unknown key id fails closed', async () => {
  const token = await signToken(base, keyPair.privateKey, { kid: 'unknown-key' });
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks()), null);
});

test('algorithm confusion and legacy HS256 are rejected', async () => {
  const token = await signToken(base, keyPair.privateKey, { alg: 'HS256' });
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks()), null);
});

test('JWKS network/server failure fails closed', async () => {
  const token = await signToken(base);
  assert.equal(await verifySupabaseJwt(token, URL, mockJwks([], 503)), null);
  assert.equal(await verifySupabaseJwt(token, URL, async () => { throw new Error('offline'); }), null);
});

test('malformed input or missing project URL fails closed', async () => {
  assert.equal(await verifySupabaseJwt('not-a-jwt', URL, mockJwks()), null);
  assert.equal(await verifySupabaseJwt('a.b', URL, mockJwks()), null);
  assert.equal(await verifySupabaseJwt('', URL, mockJwks()), null);
  assert.equal(await verifySupabaseJwt(null, URL, mockJwks()), null);
  assert.equal(await verifySupabaseJwt('x.y.z', '', mockJwks()), null);
});
