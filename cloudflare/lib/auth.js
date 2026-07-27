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
