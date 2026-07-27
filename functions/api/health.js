import { emptyResponse, jsonResponse } from '../../cloudflare/lib/http.js';

export function onRequestGet({ request, env }) {
  return jsonResponse({
    ok: true,
    service: 'affiliate-analytics',
    mode: env?.ANALYTICS_MODE || 'preview',
  }, request, env);
}

export function onRequestOptions({ request, env }) {
  return emptyResponse(request, env);
}
