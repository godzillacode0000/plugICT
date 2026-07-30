/* Browser-only affiliate checkout attribution.
   Fresh ?ref= links replace the current attribution for 30 days. */
(function () {
  'use strict';

  var STORAGE_KEY = 'plugict_ref';
  var ATTRIBUTION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
  var now = Date.now();
  var params = new URLSearchParams(window.location.search);
  var candidate = (params.get('ref') || '').trim().toLowerCase();
  var freshCode = /^[a-z0-9_-]{1,64}$/.test(candidate) ? candidate : '';
  var attribution = null;

  try {
    if (freshCode) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        code: freshCode,
        expires_at: now + ATTRIBUTION_TTL_MS,
      }));
    }

    var raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        var stored = JSON.parse(raw);
        var code = stored && typeof stored.code === 'string'
          ? stored.code.trim().toLowerCase()
          : '';
        if (
          /^[a-z0-9_-]{1,64}$/.test(code)
          && Number.isFinite(stored.expires_at)
          && stored.expires_at > now
        ) {
          attribution = { code: code, expires_at: stored.expires_at };
        } else {
          localStorage.removeItem(STORAGE_KEY);
        }
      } catch (_) {
        /* Legacy raw-code values have no trustworthy timestamp. */
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  } catch (_) {
    /* Keep this fresh page's checkout attribution if storage is unavailable. */
    if (freshCode) attribution = { code: freshCode, expires_at: now + ATTRIBUTION_TTL_MS };
  }

  if (!attribution) return;
  window.plugictStripeUrl = function (url) {
    var target = new URL(url);
    target.searchParams.set('client_reference_id', attribution.code);
    return target.href;
  };
}());
