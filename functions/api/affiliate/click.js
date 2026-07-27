import { findActiveAffiliate, insertClick } from '../../../cloudflare/lib/db.js';
import { emptyResponse, errorResponse } from '../../../cloudflare/lib/http.js';
import { hmacVisitorHash } from '../../../cloudflare/lib/auth.js';
import { parseClickPayload } from '../../../cloudflare/lib/validation.js';

export async function onRequestPost({ request, env }) {
  const contentLength = Number(request.headers.get('Content-Length') || 0);
  if (contentLength > 4096) return errorResponse(request, env, 413, 'payload too large');
  const parsed = parseClickPayload(await request.text());
  if (parsed.error) return errorResponse(request, env, parsed.status, parsed.error);

  const event = parsed.value;
  const affiliate = await findActiveAffiliate(env.DB, event.code);
  // Unknown, paused, and closed codes are intentionally indistinguishable.
  if (!affiliate) return emptyResponse(request, env);

  const salt = env.CLICK_HASH_SALT || env.ANALYTICS_HASH_SALT;
  if (!salt) return errorResponse(request, env, 503, 'analytics unavailable');
  const visitorHash = await hmacVisitorHash(event.visitor_id, salt);
  await insertClick(env.DB, event, visitorHash);
  return emptyResponse(request, env);
}

export function onRequestOptions({ request, env }) {
  return emptyResponse(request, env);
}
