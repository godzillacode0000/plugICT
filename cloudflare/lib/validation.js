export const CODE_RE = /^[a-z0-9_-]{1,64}$/i;
export const CLICK_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

export function normalizeCode(value) {
  const code = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return CODE_RE.test(code) ? code : '';
}

export function normalizeLandingPath(value) {
  if (typeof value !== 'string' || value.length > 200) return '/';
  try {
    const parsed = new URL(value || '/', 'https://plugict.invalid');
    return (parsed.pathname || '/').slice(0, 200);
  } catch {
    return '/';
  }
}

export function referrerHost(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const hostname = new URL(value.trim()).hostname.toLowerCase();
    return hostname ? hostname.slice(0, 253) : null;
  } catch {
    return null;
  }
}

export function parseClickPayload(text) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).byteLength > 4096) {
    return { error: 'payload too large', status: 413 };
  }
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return { error: 'invalid payload', status: 400 };
  }
  if (!body || Array.isArray(body) || typeof body !== 'object') {
    return { error: 'invalid payload', status: 400 };
  }
  const code = normalizeCode(body.code);
  const clickId = typeof body.click_id === 'string' ? body.click_id.trim() : '';
  const visitorId = typeof body.visitor_id === 'string' ? body.visitor_id.trim() : '';
  if (!code || !CLICK_ID_RE.test(clickId) || visitorId.length < 8 || visitorId.length > 128) {
    return { error: 'invalid payload', status: 400 };
  }
  return {
    value: {
      code,
      click_id: clickId,
      visitor_id: visitorId,
      path: normalizeLandingPath(body.path),
      referrer_host: referrerHost(body.referrer),
    },
  };
}

export function parseDays(value) {
  if (value === null || value === undefined || value === '') return 30;
  const days = Number(value);
  return Number.isInteger(days) && days >= 1 && days <= 90 ? days : null;
}

export function parseBearer(value) {
  if (typeof value !== 'string') return '';
  const match = value.match(/^Bearer\s+(.+)$/i);
  const token = match ? match[1].trim() : '';
  return token.length >= 16 && token.length <= 512 ? token : '';
}
