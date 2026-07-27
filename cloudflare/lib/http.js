const DEFAULT_ALLOWED_ORIGINS = 'http://localhost:8788,http://127.0.0.1:8788';

export function allowedOrigins(env = {}) {
  return String(env.ALLOWED_ORIGINS || DEFAULT_ALLOWED_ORIGINS)
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
}

export function corsHeaders(request, env = {}) {
  const origin = request?.headers?.get('Origin') || '';
  const headers = new Headers({ Vary: 'Origin' });
  if (origin && allowedOrigins(env).includes(origin)) {
    headers.set('Access-Control-Allow-Origin', origin);
    headers.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    headers.set('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    headers.set('Access-Control-Max-Age', '600');
  }
  return headers;
}

export function withCors(response, request, env) {
  const headers = corsHeaders(request, env);
  for (const [key, value] of response.headers) headers.set(key, value);
  return new Response(response.body, { status: response.status, headers });
}

export function jsonResponse(payload, request, env, status = 200, extra = {}) {
  const headers = corsHeaders(request, env);
  headers.set('Content-Type', 'application/json; charset=UTF-8');
  for (const [key, value] of Object.entries(extra)) headers.set(key, value);
  return new Response(JSON.stringify(payload), { status, headers });
}

export function emptyResponse(request, env, status = 204, extra = {}) {
  const headers = corsHeaders(request, env);
  for (const [key, value] of Object.entries(extra)) headers.set(key, value);
  return new Response(null, { status, headers });
}

export function errorResponse(request, env, status, message) {
  return jsonResponse({ error: message }, request, env, status, { 'Cache-Control': 'no-store' });
}
