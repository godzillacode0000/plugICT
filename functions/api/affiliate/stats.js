import { authenticateAffiliate } from '../../../cloudflare/lib/auth.js';
import { getAffiliateStats } from '../../../cloudflare/lib/db.js';
import { errorResponse, emptyResponse, jsonResponse } from '../../../cloudflare/lib/http.js';
import { parseBearer, parseDays } from '../../../cloudflare/lib/validation.js';

export async function onRequestGet({ request, env }) {
  const token = parseBearer(request.headers.get('Authorization'));
  const affiliate = await authenticateAffiliate(env.DB, token);
  if (!affiliate) return errorResponse(request, env, 401, 'affiliate authorization required');

  const days = parseDays(new URL(request.url).searchParams.get('days'));
  if (!days) return errorResponse(request, env, 400, 'days must be an integer from 1 to 90');
  const since = Math.floor(Date.now() / 1000) - (days * 86400);
  const stats = await getAffiliateStats(env.DB, affiliate.code, since);
  return jsonResponse({
    affiliate: { code: affiliate.code, name: affiliate.name },
    referral_url: `https://go.plugict.com/r/${encodeURIComponent(affiliate.code)}`,
    range_days: days,
    ...stats,
  }, request, env, 200, { 'Cache-Control': 'no-store' });
}

export function onRequestOptions({ request, env }) {
  return emptyResponse(request, env);
}
