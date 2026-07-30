import { findActiveAffiliate } from '../../cloudflare/lib/db.js';
import { normalizeCode } from '../../cloudflare/lib/validation.js';

const SITE_URL = 'https://plugict.com/';

function redirect(location) {
  return new Response(null, {
    status: 302,
    headers: {
      Location: location,
      'Cache-Control': 'no-store',
    },
  });
}

export async function onRequestGet({ env, params }) {
  const code = normalizeCode(params?.code);
  if (!code) return redirect(SITE_URL);

  const affiliate = await findActiveAffiliate(env.DB, code);
  if (!affiliate) return redirect(SITE_URL);
  return redirect(`${SITE_URL}?ref=${encodeURIComponent(affiliate.code)}`);
}
