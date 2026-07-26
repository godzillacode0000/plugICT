/* Privacy-first referral click beacon for the static PlugICT pages.
   Configure window.PLUGICT_AFFILIATE_API after deploying the API service.
   With an empty URL, this is intentionally inert. */
(function () {
  'use strict';

  var api = (window.PLUGICT_AFFILIATE_API || '').replace(/\/$/, '');
  if (!api) return;

  var params = new URLSearchParams(window.location.search);
  var ref = (params.get('ref') || '').trim().toLowerCase();
  if (!/^[a-z0-9_-]{1,64}$/.test(ref)) {
    try { ref = (localStorage.getItem('plugict_ref') || '').trim().toLowerCase(); } catch (_) {}
  }
  if (!/^[a-z0-9_-]{1,64}$/.test(ref)) return;

  function persistentId(key) {
    try {
      var existing = localStorage.getItem(key);
      if (existing) return existing;
      var created = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'v_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(key, created);
      return created;
    } catch (_) {
      return 'ephemeral_' + Date.now().toString(36);
    }
  }

  var visitorId = persistentId('plugict_affiliate_visitor');
  var clickId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : 'c_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  var body = JSON.stringify({
    code: ref,
    click_id: clickId,
    visitor_id: visitorId,
    path: window.location.pathname || '/',
    referrer: document.referrer || ''
  });
  var endpoint = api + '/api/affiliate/click';

  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
    } else {
      fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
        keepalive: true,
        credentials: 'omit'
      }).catch(function () {});
    }
  } catch (_) {}
}());
