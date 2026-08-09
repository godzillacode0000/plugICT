export async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function hmacVisitorHash(visitorId, salt) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(String(salt || '')),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const digest = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(visitorId));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function fixedLengthEqual(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string' || left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return diff === 0;
}

function base64UrlToBytes(b64) {
  const b = b64.replace(/-/g, '+').replace(/_/g, '/');
  const pad = b.length % 4 === 0 ? '' : '='.repeat(4 - (b.length % 4));
  return Uint8Array.from(atob(b + pad), (char) => char.charCodeAt(0));
}

// Verify a modern Supabase ES256 access-token JWT against the project's
// public JWKS. No private JWT secret is needed. Any malformed input, network
// failure, unsupported algorithm, key mismatch, or invalid claim fails closed.
export async function verifySupabaseJwt(token, supabaseUrl, fetchImpl = globalThis.fetch) {
  if (!token || !supabaseUrl || typeof fetchImpl !== 'function') return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const [headB64, bodyB64, sigB64] = parts;
  const signingInput = `${headB64}.${bodyB64}`;

  try {
    const baseUrl = supabaseUrl.replace(/\/+$/, '');
    const projectUrl = new URL(baseUrl);
    if (projectUrl.protocol !== 'https:') return null;

    const header = JSON.parse(new TextDecoder().decode(base64UrlToBytes(headB64)));
    if (header.alg !== 'ES256' || typeof header.kid !== 'string' || !header.kid) return null;

    const response = await fetchImpl(`${baseUrl}/auth/v1/.well-known/jwks.json`, {
      headers: { Accept: 'application/json' },
    });
    if (!response?.ok) return null;
    const jwks = await response.json();
    const jwk = Array.isArray(jwks?.keys)
      ? jwks.keys.find((candidate) => candidate?.kid === header.kid)
      : null;
    if (!jwk
      || jwk.alg !== 'ES256'
      || jwk.kty !== 'EC'
      || jwk.crv !== 'P-256'
      || (jwk.use && jwk.use !== 'sig')
      || (Array.isArray(jwk.key_ops) && !jwk.key_ops.includes('verify'))) return null;

    const publicKey = await crypto.subtle.importKey(
      'jwk',
      jwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['verify'],
    );
    const signature = base64UrlToBytes(sigB64);
    if (signature.length !== 64) return null;
    const validSignature = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' },
      publicKey,
      signature,
      new TextEncoder().encode(signingInput),
    );
    if (!validSignature) return null;

    const payload = JSON.parse(new TextDecoder().decode(base64UrlToBytes(bodyB64)));
    const now = Math.floor(Date.now() / 1000);
    const validAudience = payload.aud === 'authenticated'
      || (Array.isArray(payload.aud) && payload.aud.includes('authenticated'));
    if (typeof payload.sub !== 'string' || !payload.sub
      || typeof payload.exp !== 'number' || payload.exp <= now
      || (typeof payload.nbf === 'number' && payload.nbf > now)
      || payload.iss !== `${baseUrl}/auth/v1`
      || payload.role !== 'authenticated'
      || !validAudience) return null;

    return { userId: payload.sub, email: payload.email || '' };
  } catch {
    return null;
  }
}

export async function authenticateAffiliate(db, token) {
  if (!token) return null;
  const tokenHash = await sha256Hex(token);
  const row = await db.prepare(
    `SELECT code, display_name, status, token_hash
       FROM affiliate_codes
      WHERE token_hash = ?1 AND status = 'active'
      LIMIT 1`,
  ).bind(tokenHash).first();
  if (!row || !fixedLengthEqual(String(row.token_hash || ''), tokenHash)) return null;
  return { code: row.code, name: row.display_name };
}
