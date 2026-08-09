/* Public endpoint only — never put tokens or Stripe secrets here. */
/* Erased per release decision 2026-08-10: the affiliate API endpoint is not
   hardcoded in the client bundle; it is injected server-side per deployment.
   The public affiliate analytics beacon stays disabled until re-enabled. */
window.PLUGICT_AFFILIATE_API = '';
